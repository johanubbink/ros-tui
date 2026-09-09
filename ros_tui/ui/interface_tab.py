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

"""Shared tab layout: entity list | detail + YAML editor + controls + output log."""

from typing import Any, Iterable

import yaml
from rich.text import Text
from textual import on
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import RichLog, Static, TextArea

from ros_tui.constants import EDITOR_PARSE_DEBOUNCE_S, OUTPUT_LOG_MAX_LINES
from ros_tui.ros.graph import InterfaceEntry
from ros_tui.ros.message_yaml import (
    FieldError,
    IntrospectionError,
    build_message,
    default_yaml,
    import_type,
    request_class,
)
from ros_tui.ui.entity_tab import EntityTab
from ros_tui.ui.filterable_list import FilterableList
from ros_tui.ui.messages import PrototypeReady
from ros_tui.ui.wizards import (
    cursor_field_path,
    field_block_range,
    matched_wizard,
    render_field_block,
    replace_block,
)

_KIND_SUFFIX = {'msg': '', 'srv': ' — Request', 'action': ' — Goal'}


class InterfaceTab(EntityTab):
    """Base for the Actions/Services/Topics tabs; subclasses provide controls and verbs."""

    kind = 'msg'
    list_placeholder = 'filter…'
    entity_label = 'Entry'

    def __init__(self, bridge: Any, **kwargs):
        super().__init__(bridge, **kwargs)
        self._current: InterfaceEntry | None = None
        self._seed_cache: dict[str, str] = {}
        self._edit_cache: dict[str, str] = {}
        self._extra_cache: dict[str, Any] = {}
        self._parse_timer = None
        self._editor_error_text = ''

    # ------------------------------------------------------------------ layout

    def compose(self):
        yield FilterableList(placeholder=self.list_placeholder, classes='entity-list')
        with Vertical(classes='right-pane'):
            yield Static('', id='detail-title')
            yield Static('— select an entry on the left —', id='detail-line')
            yield from self.compose_editor_area()
            yield Static('', id='editor-error')
            with Horizontal(classes='controls'):
                yield from self.compose_controls()
            yield from self.compose_status()
            yield RichLog(
                id='output-log',
                max_lines=OUTPUT_LOG_MAX_LINES,
                wrap=True,
                markup=False,
                highlight=False,
            )

    def compose_editor_area(self) -> Iterable[Widget]:
        yield TextArea(id='editor', tab_behavior='indent', show_line_numbers=True, soft_wrap=False)

    def compose_controls(self) -> Iterable[Widget]:
        return ()

    def compose_status(self) -> Iterable[Widget]:
        return ()

    # ------------------------------------------------------------------ tab verbs (app keybindings)

    def on_selection_changed(self) -> None:
        """Refresh subclass control state after a new entry loads (override hook)."""

    def focus_content(self) -> None:
        """Re-entering the tab lands in the editor, ready to edit the message."""
        self.query_one('#editor', TextArea).focus()

    # ------------------------------------------------------------------ entries & selection

    def select_entity(self, entry: InterfaceEntry) -> None:
        """Programmatically select ``entry`` (e.g. a cross-tab jump from the Nodes tab)."""
        self.query_one(FilterableList).select_entry(entry)

    def has_selection(self) -> bool:
        return self._current is not None

    @property
    def current_entry(self) -> InterfaceEntry | None:
        return self._current

    @on(FilterableList.Selected)
    def _on_entry_selected(self, message: FilterableList.Selected) -> None:
        message.stop()
        if self._defer_selection(message.entry):
            return
        self._apply_selection(message.entry)

    def _defer_selection(self, entry: InterfaceEntry) -> bool:
        """Override to intercept a selection (e.g. a mode-choice popup). True = deferred."""
        return False

    def _apply_selection(self, entry: InterfaceEntry) -> None:
        self.minimize_list()
        self._store_current_edit()
        self._current = entry
        self.query_one('#detail-title', Static).update(f'{self.entity_label}: {entry.name}')
        type_name = entry.types[0] if entry.types else ''
        detail = self.query_one('#detail-line', Static)
        if not type_name:
            # A leaf jumped from the Nodes tab can carry no type; degrade instead of crashing.
            detail.update(Text('no type information for this entry', style='bold red'))
            self.query_one('#editor', TextArea).load_text('')
            return
        detail.update(Text(f'loading {type_name} …', style='dim'))
        self._load_prototype(entry)

    def _extra_prototype_data(self, kind: str, type_name: str) -> Any:
        """Extra data computed alongside the YAML seed in the worker (override hook)."""
        return None

    def _load_prototype(self, entry: InterfaceEntry) -> None:
        kind, entry_name = self.kind, entry.name
        type_name = entry.types[0] if entry.types else ''

        def load() -> None:
            try:
                seed_text = default_yaml(kind, type_name)
                extra = self._extra_prototype_data(kind, type_name)
                error = ''
            except IntrospectionError as introspection_error:
                seed_text, extra, error = '', None, str(introspection_error)
            self.post_message(PrototypeReady(entry_name, type_name, seed_text, error, extra))

        self.run_worker(load, thread=True, exclusive=True, group='type-load')

    def on_prototype_ready(self, message: PrototypeReady) -> None:
        message.stop()
        if self._current is None or message.entry_name != self._current.name:
            return  # Stale result from a superseded selection.
        detail = self.query_one('#detail-line', Static)
        editor = self.query_one('#editor', TextArea)
        if message.error:
            detail.update(Text(message.error, style='bold red'))
            editor.load_text('')
            return
        self._seed_cache[message.entry_name] = message.seed_text
        self._extra_cache[message.entry_name] = message.extra
        types_note = ''
        if len(self._current.types) > 1:
            types_note = f'  (+{len(self._current.types) - 1} more types)'
        detail.update(f'{message.type_name}{_KIND_SUFFIX[self.kind]}{types_note}')
        editor.load_text(self._edit_cache.get(message.entry_name, message.seed_text))
        self._set_editor_error('')
        self.on_selection_changed()

    def _store_current_edit(self) -> None:
        if self._current is None:
            return
        seed = self._seed_cache.get(self._current.name)
        if seed is None:
            return
        text = self.query_one('#editor', TextArea).text
        if text != seed:
            self._edit_cache[self._current.name] = text
        else:
            self._edit_cache.pop(self._current.name, None)

    def reset_editor(self) -> None:
        if self._current is None:
            return
        seed = self._seed_cache.get(self._current.name)
        if seed is None:
            return
        self._edit_cache.pop(self._current.name, None)
        self.query_one('#editor', TextArea).load_text(seed)
        self._set_editor_error('')

    # ------------------------------------------------------------------ field wizard

    def open_field_wizard(self) -> None:
        """Open a fill-in wizard for the field on the editor's cursor line, if one is registered.

        Reusable across editor tabs: reads the message structure a tab caches in ``_extra_cache``
        by returning ``message_structure`` from ``_extra_prototype_data``. No-ops when no
        structure is available, so tabs that don't opt in are unaffected.
        """
        if self._current is None:
            return
        structure = self._extra_cache.get(self._current.name)
        if not structure:
            return
        editor = self.query_one('#editor', TextArea)
        text = editor.text
        path = cursor_field_path(text, editor.cursor_location[0])
        match = matched_wizard(structure, path)
        if match is None:
            self.write_log('no fill wizard for this field', 'dim')
            return
        matched_path, wizard_class = match
        block = field_block_range(text, matched_path)
        current_value = None
        if block is not None:
            start, end, indent = block
            snippet = '\n'.join(line[indent:] for line in text.splitlines()[start:end])
            try:
                current_value = (yaml.safe_load(snippet) or {}).get(matched_path[-1])
            except yaml.YAMLError:
                current_value = None

        def on_dismiss(value) -> None:
            if value is None:
                return
            self._apply_wizard_value(matched_path, value)

        self.app.push_screen(wizard_class(current_value), on_dismiss)

    def _apply_wizard_value(self, matched_path: list[str], value) -> None:
        editor = self.query_one('#editor', TextArea)
        block = field_block_range(editor.text, matched_path)
        if block is None:
            return
        start, end, indent = block
        new_block = render_field_block(matched_path[-1], value, indent)
        new_text, cursor_row = replace_block(editor.text, start, end, new_block)
        editor.load_text(new_text)
        editor.move_cursor((cursor_row, 0))
        editor.focus()

    # ------------------------------------------------------------------ editor parsing

    @on(TextArea.Changed, '#editor')
    def _on_editor_changed(self, event: TextArea.Changed) -> None:
        event.stop()
        if self._parse_timer is not None:
            self._parse_timer.stop()
        self._parse_timer = self.set_timer(EDITOR_PARSE_DEBOUNCE_S, self._check_yaml_structure)

    def _check_yaml_structure(self) -> None:
        try:
            yaml.safe_load(self.query_one('#editor', TextArea).text)
        except yaml.YAMLError as error:
            self._set_editor_error(self._yaml_error_text(error))
        else:
            # Only clear errors this check produced — a fresh button-press error (field
            # path, rate bounds, …) must survive a debounce timer scheduled before it.
            if self._editor_error_text.startswith('YAML error'):
                self._set_editor_error('')

    def build_from_editor(self) -> tuple[Any, tuple] | None:
        """Parse the editor into a checked message; on failure show the error and return None."""
        if self._current is None:
            self._set_editor_error('select an entry on the left first')
            return None
        try:
            interface = import_type(self.kind, self._current.types[0])
            values = yaml.safe_load(self.query_one('#editor', TextArea).text)
            message, time_setters = build_message(request_class(self.kind, interface), values)
        except yaml.YAMLError as error:
            self._set_editor_error(self._yaml_error_text(error))
            return None
        except (IntrospectionError, FieldError) as error:
            self._set_editor_error(str(error))
            return None
        self._set_editor_error('')
        return message, tuple(time_setters)

    @staticmethod
    def _yaml_error_text(error: yaml.YAMLError) -> str:
        mark = getattr(error, 'problem_mark', None)
        problem = getattr(error, 'problem', None) or str(error)
        if mark is not None:
            return f'YAML error line {mark.line + 1}: {problem}'
        return f'YAML error: {problem}'

    def _set_editor_error(self, text: str) -> None:
        self._editor_error_text = text
        error_line = self.query_one('#editor-error', Static)
        error_line.update(Text(text, style='bold red') if text else '')
        error_line.display = bool(text)

    # ------------------------------------------------------------------ output log

    def write_log(self, text: str, style: str = '') -> None:
        log = self.query_one('#output-log', RichLog)
        log.write(Text(text, style=style) if style else text)

    def clear_log(self) -> None:
        self.query_one('#output-log', RichLog).clear()

    # ------------------------------------------------------------------ future results

    @staticmethod
    def _error_text(error: BaseException) -> str:
        """Human-readable text for an exception raised on the ROS thread."""
        return str(error) or type(error).__name__

    @classmethod
    def _future_error(cls, done_future) -> str | None:
        """None if the future succeeded, else its error text (for log/command callbacks)."""
        try:
            done_future.result()
            return None
        except BaseException as error:  # noqa: BLE001 - rendered in the log
            return cls._error_text(error)
