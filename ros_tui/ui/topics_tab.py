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

"""Topics tab: publish once or at a fixed rate, and echo a topic with stats."""

from rich.text import Text
from textual import on
from textual.widgets import Button, Input, Static

from ros_tui.constants import (
    ECHO_MAX_RENDER_PER_TICK,
    ECHO_RENDER_PERIOD_S,
    PUBLISH_RATE_MAX_HZ,
    PUBLISH_RATE_MIN_HZ,
)
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.message_yaml import to_truncated_yaml
from ros_tui.ui.interface_tab import InterfaceTab
from ros_tui.ui.messages import PublishCompleted


class TopicsTab(InterfaceTab):
    kind = 'msg'
    list_placeholder = 'filter topics…'

    def __init__(self, bridge, **kwargs):
        super().__init__(bridge, **kwargs)
        self._rate_topics: dict[str, float] = {}
        self._echo_topic: str | None = None
        self._echo_buffer: EchoBuffer | None = None
        self._echo_paused = False

    def compose_controls(self):
        yield Button('Publish', id='publish-button', variant='primary')
        yield Input(value='10', id='rate-input', tooltip='publish rate in Hz')
        yield Button('Start rate', id='rate-button')
        yield Button('Echo', id='echo-button')
        yield Button('Pause', id='pause-button', disabled=True)

    def compose_status(self):
        yield Static('', id='topics-status')

    def on_mount(self) -> None:
        self.set_interval(ECHO_RENDER_PERIOD_S, self._drain_echo)

    def on_selection_changed(self) -> None:
        self._update_controls()

    # ------------------------------------------------------------------ publishing

    @on(Button.Pressed, '#publish-button')
    def _on_publish_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.primary_action()

    def primary_action(self) -> None:
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
        """ctrl+k stops the selected topic's periodic publisher (if any)."""
        if self._current is not None and self._current.name in self._rate_topics:
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
        if self._current is None:
            self._set_editor_error('select a topic on the left first')
            return
        if self._echo_topic == self._current.name:
            self._stop_echo()
        else:
            self._start_echo(self._current.name, self._current.types[0])

    @on(Button.Pressed, '#pause-button')
    def _on_pause_pressed(self, event: Button.Pressed) -> None:
        event.stop()
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
        for received_message in messages:
            self.write_log(f'─── {self._echo_topic}', style='dim')
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
