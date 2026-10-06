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

"""The entry kinds: one `EntryProvider` per kind, and the router NavState talks to.

`NavState` holds a single provider. `EntryRouter` is that provider in the app: it hands each call
to the provider of the tab's kind (`node.NodeEntry` for nodes) and to the default `EntryProvider`
for the kinds that aren't built yet (the default also keeps a topic's Echo / Publish mode). Pure
Python: no textual, no rclpy. Bridge results reach a provider through `post`, which runs a function
on the UI thread (see `NextApp`).
"""

from typing import Any

from ros_tui.ui.entries.base import Post
from ros_tui.ui.entries.node import NodeEntry
from ros_tui.ui.nav import Area, Commit, Editing, EntryProvider, NavState, Tab, UndoEntry


class EntryRouter(EntryProvider):
    """Routes every EntryProvider call by the tab's kind; undo by the kind of the tab that owns it."""

    def __init__(self, providers: dict[str, EntryProvider], default: EntryProvider | None = None):
        super().__init__()
        self.providers = providers
        self.default = default or EntryProvider()

    def for_tab(self, tab: Tab | None) -> EntryProvider:
        return self.providers.get(tab.kind, self.default) if tab else self.default

    def on_open(self, nav: NavState, tab: Tab) -> None:
        self.for_tab(tab).on_open(nav, tab)

    def mode(self, tab: Tab) -> str | None:
        return self.for_tab(tab).mode(tab)

    def screen(self, tab: Tab) -> str:
        return self.for_tab(tab).screen(tab)

    def areas(self, tab: Tab) -> tuple[Area, ...]:
        return self.for_tab(tab).areas(tab)

    def row_count(self, tab: Tab, area: Area) -> int:
        return self.for_tab(tab).row_count(tab, area)

    def start_edit(self, tab: Tab, area: Area, row: int, clear: bool) -> Editing | None:
        return self.for_tab(tab).start_edit(tab, area, row, clear)

    def commit_edit(self, tab: Tab, editing: Editing) -> Commit:
        return self.for_tab(tab).commit_edit(tab, editing)

    def activate_row(self, nav: NavState, tab: Tab, area: Area, row: int, how: str) -> bool:
        return self.for_tab(tab).activate_row(nav, tab, area, row, how)

    def leave_area(self, tab: Tab, area: Area) -> str | None:
        return self.for_tab(tab).leave_area(tab, area)

    def esc_label(self, tab: Tab, area: Area) -> str | None:
        return self.for_tab(tab).esc_label(tab, area)

    def helper_name(self, tab: Tab, area: Area, row: int) -> str | None:
        return self.for_tab(tab).helper_name(tab, area, row)

    def label_vars(self, tab: Tab | None) -> dict[str, Any]:
        return self.for_tab(tab).label_vars(tab)

    def verb(self, nav: NavState, tab: Tab | None, name: str, how: str, arg: Any = None) -> bool:
        return self.for_tab(tab).verb(nav, tab, name, how, arg)

    def undo(self, nav: NavState, entry: UndoEntry) -> str:
        kind = entry.owner.split(':', 1)[0]
        return self.providers.get(kind, self.default).undo(nav, entry)


def entry_router(bridge: Any, post: Post | None = None) -> EntryRouter:
    """The app's provider: the built entry kinds over `bridge`, the default for the rest."""
    return EntryRouter({'nodes': NodeEntry(bridge, post)})
