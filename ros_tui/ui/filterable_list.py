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
                if filter_text in entry.name.lower() or filter_text in entry.types[0].lower()
            ]
        else:
            matching = list(self._entries)
        option_list.clear_options()
        option_list.add_options([Option(entry.name, id=entry.name) for entry in matching])
        if previous_id is not None:
            for index, entry in enumerate(matching):
                if entry.name == previous_id:
                    option_list.highlighted = index
                    break
        self.border_subtitle = f'{len(matching)}/{len(self._entries)}'
