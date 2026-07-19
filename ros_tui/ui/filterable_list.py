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

"""Filterable entity list: an Input over an OptionList, debounced, selection-preserving."""

from rich.table import Table
from rich.text import Text
from textual import on
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from ros_tui.constants import FILTER_DEBOUNCE_S
from ros_tui.ros.graph import InterfaceEntry


class FilterableList(Vertical):
    class Selected(Message):
        def __init__(self, entry: InterfaceEntry):
            super().__init__()
            self.entry = entry

    def __init__(self, placeholder: str = 'filter…', **kwargs):
        super().__init__(**kwargs)
        self._placeholder = placeholder
        self._entries: tuple[InterfaceEntry, ...] = ()
        self._by_name: dict[str, InterfaceEntry] = {}
        self._debounce_timer = None

    def compose(self):
        yield Input(placeholder=self._placeholder, id='filter-input')
        yield OptionList(id='entity-list')

    def set_entries(self, entries: tuple[InterfaceEntry, ...]) -> None:
        if entries == self._entries:
            return
        self._entries = entries
        self._by_name = {entry.name: entry for entry in entries}
        self._refresh_options()

    def focus_filter(self) -> None:
        self.query_one('#filter-input', Input).focus()

    def select_entry(self, entry: InterfaceEntry) -> None:
        """Highlight ``entry`` (clearing the filter so it is visible) and emit Selected.

        Used for cross-tab jumps. If the entry is not in this list (e.g. a service/action
        client with no server in the graph) the highlight is skipped, but Selected still
        fires so the destination tab can seed its editor from the entry's type.
        """
        filter_input = self.query_one('#filter-input', Input)
        if filter_input.value:
            filter_input.value = ''  # Schedules a debounced refresh…
            self._refresh_options()  # …but refresh now so the option is present immediately.
        option_list = self.query_one('#entity-list', OptionList)
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == entry.name:
                option_list.highlighted = index
                break
        self.post_message(self.Selected(entry))

    @on(Input.Changed, '#filter-input')
    def _on_filter_changed(self, event: Input.Changed) -> None:
        event.stop()
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
        self._debounce_timer = self.set_timer(FILTER_DEBOUNCE_S, self._refresh_options)

    @on(OptionList.OptionSelected, '#entity-list')
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        entry = self._by_name.get(event.option.id)
        if entry is not None:
            self.post_message(self.Selected(entry))

    @on(Input.Submitted, '#filter-input')
    def _on_filter_submitted(self, event: Input.Submitted) -> None:
        """Enter in the filter selects the currently highlighted match."""
        event.stop()
        option_list = self.query_one('#entity-list', OptionList)
        if option_list.highlighted is None:
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        entry = self._by_name.get(option.id)
        if entry is not None:
            self.post_message(self.Selected(entry))

    def on_key(self, event) -> None:
        """While the filter input is focused, up/down move the list highlight so the
        whole search→select flow works without leaving the input or using the mouse."""
        if event.key not in ('up', 'down'):
            return
        focused = self.app.focused
        if focused is None or focused.id != 'filter-input':
            return
        option_list = self.query_one('#entity-list', OptionList)
        if event.key == 'down':
            option_list.action_cursor_down()
        else:
            option_list.action_cursor_up()
        event.stop()
        event.prevent_default()

    @staticmethod
    def _render_prompt(entry: InterfaceEntry):
        """Row content: entry name left-aligned (kept in full), message type on the
        right in a distinct dim-cyan. The type column absorbs the slack and truncates
        first, so a narrow list clips the (less important) type before the name."""
        if not entry.types:
            return entry.name
        grid = Table.grid(expand=True)
        grid.add_column(no_wrap=True, overflow='ellipsis')  # name: priority
        grid.add_column(justify='right', no_wrap=True, overflow='ellipsis', ratio=1)
        grid.add_row(entry.name, Text('  ' + entry.types[0], style='dim cyan'))
        return grid

    def _refresh_options(self) -> None:
        option_list = self.query_one('#entity-list', OptionList)
        previous_id = None
        if option_list.highlighted is not None:
            previous_id = option_list.get_option_at_index(option_list.highlighted).id
        filter_text = self.query_one('#filter-input', Input).value.strip().lower()
        if filter_text:
            matching = [
                entry
                for entry in self._entries
                if filter_text in entry.name.lower()
                or (entry.types and filter_text in entry.types[0].lower())
            ]
        else:
            matching = list(self._entries)
        option_list.clear_options()
        # Names are the Option id, which must be unique; dedup defensively so a
        # repeated name (e.g. duplicate node names) can never raise DuplicateID.
        seen = set()
        options = []
        for entry in matching:
            if entry.name in seen:
                continue
            seen.add(entry.name)
            options.append(Option(self._render_prompt(entry), id=entry.name))
        option_list.add_options(options)
        restored = False
        if previous_id is not None:
            for index, entry in enumerate(matching):
                if entry.name == previous_id:
                    option_list.highlighted = index
                    restored = True
                    break
        # Auto-select the first match so Enter always has a target (Textual otherwise
        # leaves highlighted=None until the user arrow-keys or clicks).
        if not restored and option_list.option_count > 0:
            option_list.highlighted = 0
        self.border_subtitle = f'{len(matching)}/{len(self._entries)}'
