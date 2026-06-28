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

_KIND_SUFFIX = {'msg': '', 'srv': ' — Request', 'action': ' — Goal'}


class InterfaceTab(EntityTab):
    """Base for the Actions/Services/Topics tabs; subclasses provide controls and verbs."""

    kind = 'msg'
    list_placeholder = 'filter…'

    def __init__(self, bridge: Any, **kwargs):
        super().__init__(bridge, **kwargs)
        self._current: InterfaceEntry | None = None
        self._seed_cache: dict[str, str] = {}
        self._edit_cache: dict[str, str] = {}
        self._parse_timer = None
        self._editor_error_text = ''

    # ------------------------------------------------------------------ layout

    def compose(self):
        yield FilterableList(placeholder=self.list_placeholder, classes='entity-list')
        with Vertical(classes='right-pane'):
            yield Static('— select an entry on the left —', id='detail-line')
            yield TextArea(
                id='editor', tab_behavior='indent', show_line_numbers=True, soft_wrap=False
            )
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

    def compose_controls(self) -> Iterable[Widget]:
        return ()

    def compose_status(self) -> Iterable[Widget]:
        return ()

    # ------------------------------------------------------------------ tab verbs (app keybindings)

    def on_selection_changed(self) -> None:
        """Refresh subclass control state after a new entry loads (override hook)."""

    # ------------------------------------------------------------------ entries & selection

    def select_entity(self, entry: InterfaceEntry) -> None:
        """Programmatically select ``entry`` (e.g. a cross-tab jump from the Nodes tab)."""
        self.query_one(FilterableList).select_entry(entry)

    @property
    def current_entry(self) -> InterfaceEntry | None:
        return self._current

    @on(FilterableList.Selected)
    def _on_entry_selected(self, message: FilterableList.Selected) -> None:
        message.stop()
        self._store_current_edit()
        self._current = message.entry
        type_name = message.entry.types[0] if message.entry.types else ''
        detail = self.query_one('#detail-line', Static)
        if not type_name:
            # A leaf jumped from the Nodes tab can carry no type; degrade instead of crashing.
            detail.update(Text('no type information for this entry', style='bold red'))
            self.query_one('#editor', TextArea).load_text('')
            return
        detail.update(Text(f'loading {type_name} …', style='dim'))
        self._load_prototype(message.entry)

    def _load_prototype(self, entry: InterfaceEntry) -> None:
        kind, entry_name = self.kind, entry.name
        type_name = entry.types[0] if entry.types else ''

        def load() -> None:
            try:
                seed_text = default_yaml(kind, type_name)
                error = ''
            except IntrospectionError as introspection_error:
                seed_text, error = '', str(introspection_error)
            self.post_message(PrototypeReady(entry_name, type_name, seed_text, error))

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
        types_note = ''
        if len(self._current.types) > 1:
            types_note = f'  (+{len(self._current.types) - 1} more types)'
        detail.update(
            Text(f'{message.type_name}{_KIND_SUFFIX[self.kind]}{types_note}', style='bold')
        )
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
