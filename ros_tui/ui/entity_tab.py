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

"""Shared base for every tab: a bridge, a left-hand entity list, and the verb hooks."""

from typing import Any

from textual.containers import Horizontal

from ros_tui.ros.graph import InterfaceEntry
from ros_tui.ui.filterable_list import FilterableList


class EntityTab(Horizontal):
    """Common contract for all four tabs.

    Each tab lays out a :class:`FilterableList` on the left, holds the shared ``RosBridge``,
    and exposes the verb hooks the app routes its keybindings to. The app resolves the active
    pane to an ``EntityTab`` and calls these hooks uniformly — they are no-ops here so a tab
    only overrides the verbs it actually supports (e.g. the Nodes tab has no editor to reset).
    """

    def __init__(self, bridge: Any, **kwargs):
        super().__init__(**kwargs)
        self._bridge = bridge

    def set_entries(self, entries: tuple[InterfaceEntry, ...]) -> None:
        self.query_one(FilterableList).set_entries(entries)

    def focus_filter(self) -> None:
        self.query_one(FilterableList).focus_filter()

    def select_entity(self, entry: InterfaceEntry) -> None:
        """Programmatically select ``entry`` (cross-tab jump target).

        Only the interface tabs are jump destinations; tabs that are merely a jump
        *source* (e.g. the Nodes tab) inherit this no-op.
        """

    # Verb hooks dispatched from the app keybindings; overridden per tab as needed.
    def primary_action(self) -> None:
        """ctrl+s — Send goal / Call / Publish once / Set parameter."""

    def secondary_action(self) -> None:
        """ctrl+k — Cancel goal / Stop periodic publish / Refresh node."""

    def reset_editor(self) -> None:
        """ctrl+r — reset the editor to the message defaults (no editor → no-op)."""

    def clear_log(self) -> None:
        """ctrl+l — clear the tab's output/status region."""
