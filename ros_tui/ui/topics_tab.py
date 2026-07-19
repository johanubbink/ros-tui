#!/usr/bin/env python3
# Copyright 2026 Johan Ubbink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Topics tab: publish or subscribe to a topic, chosen per topic via a mode popup."""

from dataclasses import dataclass

from rich.text import Text
from textual import on
from textual.widgets import Button, Input, Static, TextArea, Tree

from ros_tui.constants import (
    ECHO_MAX_RENDER_PER_TICK,
    ECHO_RENDER_PERIOD_S,
    PUBLISH_RATE_MAX_HZ,
    PUBLISH_RATE_MIN_HZ,
)
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.graph import InterfaceEntry
from ros_tui.ros.message_yaml import (
    FieldNode,
    field_path,
    message_structure,
    to_filtered_yaml,
    to_truncated_yaml,
)
from ros_tui.ui.interface_tab import InterfaceTab
from ros_tui.ui.messages import PublishCompleted
from ros_tui.ui.topic_mode_popup import TopicModePopup

_CHECKBOX = {'checked': '[x]', 'unchecked': '[ ]', 'partial': '[~]'}


@dataclass(frozen=True)
class _FieldNodeData:
    """Payload attached to each structure-tree node: its dotted path and label pieces."""

    path: str
    name: str
    type_label: str


def _leaf_paths_under(node) -> list[str]:
    """Every leaf field path at or below ``node`` (the tree root carries no data)."""
    if node.data is None:
        return [path for child in node.children for path in _leaf_paths_under(child)]
    if not node.children:
        return [node.data.path]
    return [path for child in node.children for path in _leaf_paths_under(child)]


def _node_state(node, selected: set[str] | None) -> str:
    """Tri-state of a node's checkbox, derived from how many of its leaves are selected."""
    if not selected:
        return 'checked'  # No selection means "show everything".
    leaves = _leaf_paths_under(node)
    count = sum(1 for leaf in leaves if leaf in selected)
    if count == len(leaves):
        return 'checked'
    if count == 0:
        return 'unchecked'
    return 'partial'


class TopicsTab(InterfaceTab):
    kind = 'msg'
    list_placeholder = 'filter topics…'
    entity_label = 'Topic'

    def __init__(self, bridge, **kwargs):
        super().__init__(bridge, **kwargs)
        self._mode = 'publish'  # 'publish' | 'subscribe'
        self._rate_topics: dict[str, float] = {}
        self._echo_topic: str | None = None
        self._echo_buffer: EchoBuffer | None = None
        self._echo_paused = False
        self._topic_selection: dict[str, set[str]] = {}  # topic -> selected leaf paths

    def compose_editor_area(self):
        yield TextArea(id='editor', tab_behavior='indent', show_line_numbers=True, soft_wrap=False)
        yield Tree('message', id='topic-structure-tree')

    def compose_controls(self):
        yield Button('Publish', id='publish-button', variant='primary')
        yield Input(value='10', id='rate-input', tooltip='publish rate in Hz')
        yield Button('Start rate', id='rate-button')
        yield Button('Echo', id='echo-button')
        yield Button('Pause', id='pause-button', disabled=True)
        yield Button('→ Subscribe', id='mode-toggle-button')

    def compose_status(self):
        yield Static('', id='topics-status')

    def on_mount(self) -> None:
        tree = self.query_one('#topic-structure-tree', Tree)
        tree.show_root = False
        # Selecting a branch toggles its checkbox; keep it from also expand/collapsing
        # (Tree's built-in auto_expand runs on NodeSelected before our handler).
        tree.auto_expand = False
        self.set_interval(ECHO_RENDER_PERIOD_S, self._drain_echo)
        self._apply_mode_layout()

    # ------------------------------------------------------------------ mode selection

    def _defer_selection(self, entry: InterfaceEntry) -> bool:
        if not entry.types:
            return False  # No type info; let the base "no type" path handle it.
        counts_future = self._bridge.topic_endpoint_counts(entry.name)

        def on_dismiss(mode: str | None) -> None:
            if mode is None:
                return  # Escape: leave the previous topic/mode view untouched.
            self._mode = mode
            self._apply_selection(entry)

        self.app.push_screen(TopicModePopup(entry, counts_future), on_dismiss)
        return True

    def _extra_prototype_data(self, kind: str, type_name: str):
        return message_structure(kind, type_name)

    def on_selection_changed(self) -> None:
        self._update_controls()
        self._enter_mode(self._mode)

    def _enter_mode(self, mode: str) -> None:
        self._mode = mode
        self._apply_mode_layout()
        if mode == 'subscribe':
            self._populate_structure_tree()
            self.query_one('#topic-structure-tree', Tree).focus()
        else:
            self.query_one('#editor', TextArea).focus()

    def _apply_mode_layout(self) -> None:
        right_pane = self.query_one('.right-pane')
        right_pane.remove_class('mode-publish', 'mode-subscribe')
        right_pane.add_class(f'mode-{self._mode}')
        is_publish = self._mode == 'publish'
        self.query_one('#editor', TextArea).display = is_publish
        self.query_one('#topic-structure-tree', Tree).display = not is_publish
        for widget_id in ('#publish-button', '#rate-input', '#rate-button'):
            self.query_one(widget_id).display = is_publish
        for widget_id in ('#echo-button', '#pause-button'):
            self.query_one(widget_id).display = not is_publish
        self.query_one('#mode-toggle-button', Button).label = (
            '→ Subscribe' if is_publish else '→ Publish'
        )

    @on(Button.Pressed, '#mode-toggle-button')
    def _on_mode_toggle_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        # Switching out of a mode stops that mode's live operation.
        if self._mode == 'subscribe':
            self._stop_echo()
            self._enter_mode('publish')
        else:
            if self._current is not None and self._current.name in self._rate_topics:
                self._stop_rate(self._current.name)
            self._enter_mode('subscribe')

    def _populate_structure_tree(self) -> None:
        tree = self.query_one('#topic-structure-tree', Tree)
        tree.clear()
        fields = self._extra_cache.get(self._current.name) if self._current else None
        selected = self._topic_selection.get(self._current.name) if self._current else None
        for field in fields or ():
            self._add_field_node(tree.root, field, '', selected)

    def _add_field_node(self, parent, field: FieldNode, path_prefix: str, selected) -> None:
        path = field_path(path_prefix, field.name)
        data = _FieldNodeData(path, field.name, field.type_label)
        if field.children:
            node = parent.add(Text(''), data=data, expand=False)
            for child in field.children:
                self._add_field_node(node, child, path, selected)
        else:
            node = parent.add_leaf(Text(''), data=data)
        self._relabel(node, selected)

    def _relabel(self, node, selected) -> None:
        state = _node_state(node, selected)
        node.set_label(Text(f'{_CHECKBOX[state]} {node.data.name}: {node.data.type_label}'))

    def _refresh_labels(self, node, selected) -> None:
        self._relabel(node, selected)
        for child in node.children:
            self._refresh_labels(child, selected)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        node = event.node
        if node.data is None or self._current is None:
            return
        tree = self.query_one('#topic-structure-tree', Tree)
        name = self._current.name
        selected = self._topic_selection.get(name)
        if not selected:  # Absent or empty: materialize "all selected", then toggle from there.
            selected = set(_leaf_paths_under(tree.root))
            self._topic_selection[name] = selected
        leaves = _leaf_paths_under(node)
        if any(leaf not in selected for leaf in leaves):
            selected.update(leaves)  # Partial/unchecked -> select the whole subtree.
        else:
            selected.difference_update(leaves)  # Fully selected -> clear it.
        for child in tree.root.children:
            self._refresh_labels(child, selected)

    def reset_editor(self) -> None:
        """ctrl+r: in subscribe mode clear the field selection (echo everything again)."""
        if self._mode == 'subscribe':
            if self._current is not None:
                self._topic_selection.pop(self._current.name, None)
                self._populate_structure_tree()
            return
        super().reset_editor()

    # ------------------------------------------------------------------ publishing

    @on(Button.Pressed, '#publish-button')
    def _on_publish_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._publish_once()

    def primary_action(self) -> None:
        if self._mode == 'subscribe':
            self._toggle_echo()
        else:
            self._publish_once()

    def _publish_once(self) -> None:
        built = self.build_from_editor()
        if built is None:
            return
        message, time_setters = built
        name, type_name = self._current.name, self._current.types[0]
        future = self._bridge.publish_once(name, type_name, message, time_setters)
        self._report_when_done(future, name, 'publish')

    @on(Button.Pressed, '#rate-button')
    def _on_rate_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = self._current.name if self._current else None
        if name is None:
            self._set_editor_error('select a topic on the left first')
            return
        if name in self._rate_topics:
            self._stop_rate(name)
        else:
            self._start_rate(name)

    def secondary_action(self) -> None:
        """ctrl+k: pause/resume the echo (subscribe) or stop the periodic publisher (publish)."""
        if self._mode == 'subscribe':
            self._toggle_pause()
        elif self._current is not None and self._current.name in self._rate_topics:
            self._stop_rate(self._current.name)

    def _start_rate(self, name: str) -> None:
        rate_text = self.query_one('#rate-input', Input).value.strip()
        try:
            rate_hz = float(rate_text)
        except ValueError:
            self._set_editor_error(f"rate '{rate_text}' is not a number")
            return
        if not PUBLISH_RATE_MIN_HZ <= rate_hz <= PUBLISH_RATE_MAX_HZ:
            self._set_editor_error(
                f'rate must be within [{PUBLISH_RATE_MIN_HZ:g}, {PUBLISH_RATE_MAX_HZ:g}] Hz'
            )
            return
        built = self.build_from_editor()
        if built is None:
            return
        message, time_setters = built
        future = self._bridge.start_periodic_publish(
            name, self._current.types[0], message, rate_hz, time_setters
        )
        self._report_when_done(future, name, f'start {rate_hz:g} Hz')
        self._rate_topics[name] = rate_hz
        self.write_log(f'publishing {name} @ {rate_hz:g} Hz (edits apply after restart)', 'cyan')
        self._update_controls()

    def _stop_rate(self, name: str) -> None:
        future = self._bridge.stop_periodic_publish(name)
        self._report_when_done(future, name, 'stop rate')
        self._rate_topics.pop(name, None)
        self.write_log(f'stopped publishing {name}', 'cyan')
        self._update_controls()

    def on_publish_completed(self, message: PublishCompleted) -> None:
        message.stop()
        if message.error is not None:
            self.write_log(f'✗ {message.label} {message.topic_name}: {message.error}', 'bold red')
            if message.label.startswith('start') or message.label == 'stop rate':
                self._rate_topics.pop(message.topic_name, None)
            if message.label == 'echo' and self._echo_topic == message.topic_name:
                self._echo_topic = None
                self._echo_buffer = None
                self.query_one('#pause-button', Button).disabled = True
            self._update_controls()
        elif message.label == 'publish':
            self.write_log(f'✓ published once on {message.topic_name}', 'green')

    def _report_when_done(self, future, name: str, label: str) -> None:
        """Post a PublishCompleted (with any error text) once ``future`` resolves."""
        future.add_done_callback(
            lambda done: self.post_message(PublishCompleted(name, label, self._future_error(done)))
        )

    # ------------------------------------------------------------------ echo

    @on(Button.Pressed, '#echo-button')
    def _on_echo_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._toggle_echo()

    @on(Button.Pressed, '#pause-button')
    def _on_pause_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._toggle_pause()

    def _toggle_echo(self) -> None:
        if self._current is None:
            self._set_editor_error('select a topic on the left first')
            return
        if self._echo_topic == self._current.name:
            self._stop_echo()
        else:
            self._start_echo(self._current.name, self._current.types[0])

    def _toggle_pause(self) -> None:
        self._echo_paused = not self._echo_paused
        self.query_one('#pause-button', Button).label = 'Resume' if self._echo_paused else 'Pause'

    def _start_echo(self, name: str, type_name: str) -> None:
        if self._echo_topic is not None:
            self._stop_echo()
        self._echo_buffer = EchoBuffer()
        self._echo_topic = name
        self._echo_paused = False
        future = self._bridge.subscribe(name, type_name, self._echo_buffer)
        self._report_when_done(future, name, 'echo')
        self.write_log(f'echo started on {name}', 'cyan')
        self.query_one('#pause-button', Button).disabled = False
        self.query_one('#pause-button', Button).label = 'Pause'
        self._update_controls()

    def _stop_echo(self) -> None:
        if self._echo_topic is None:
            return
        name = self._echo_topic
        future = self._bridge.unsubscribe(name)
        self._report_when_done(future, name, 'stop echo')
        self.write_log(f'echo stopped on {name}', 'cyan')
        self._echo_topic = None
        self._echo_buffer = None
        self.query_one('#pause-button', Button).disabled = True
        self._update_controls()

    def _drain_echo(self) -> None:
        if self._echo_buffer is None:
            return
        messages, received, dropped, rate_hz = self._echo_buffer.drain()
        status = f'echo {self._echo_topic} · {received} msgs · {rate_hz:.1f} Hz · dropped {dropped}'
        self._update_status(echo_text=status)
        if self._echo_paused or not messages:
            return
        if len(messages) > ECHO_MAX_RENDER_PER_TICK:
            hidden = len(messages) - ECHO_MAX_RENDER_PER_TICK
            self.write_log(f'(+{hidden} messages not shown)', style='dim')
            messages = messages[-ECHO_MAX_RENDER_PER_TICK:]
        selected = self._topic_selection.get(self._echo_topic)
        for received_message in messages:
            self.write_log(f'─── {self._echo_topic}', style='dim')
            if selected:
                self.write_log(to_filtered_yaml(received_message, selected))
            else:
                self.write_log(to_truncated_yaml(received_message))

    # ------------------------------------------------------------------ status & controls

    def _update_controls(self) -> None:
        selected = self._current.name if self._current else None
        rate_button = self.query_one('#rate-button', Button)
        rate_button.label = 'Stop rate' if selected in self._rate_topics else 'Start rate'
        echo_button = self.query_one('#echo-button', Button)
        echo_button.label = 'Stop echo' if selected == self._echo_topic else 'Echo'
        self._update_status()

    def _update_status(self, echo_text: str = '') -> None:
        parts = []
        if self._rate_topics:
            publishing = ', '.join(
                f'{name} @ {rate:g} Hz' for name, rate in sorted(self._rate_topics.items())
            )
            parts.append(f'publishing: {publishing}')
        if echo_text:
            parts.append(echo_text)
        elif self._echo_topic is not None:
            parts.append(f'echo {self._echo_topic}')
        self.query_one('#topics-status', Static).update(Text(' · '.join(parts), style='dim'))
