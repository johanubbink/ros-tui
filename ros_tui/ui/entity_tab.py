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
        self.maximize_list()
        self.query_one(FilterableList).focus_filter()

    def has_selection(self) -> bool:
        """True if this tab has a selected entity, i.e. its detail view holds content.

        The app uses this to decide, on tab activation, whether to land in browse mode
        (list focused) or restore the previously selected item's detail view. A tab that
        never populates a detail view keeps the default of no selection.
        """
        return False

    def maximize_list(self) -> None:
        """Browse mode: the entity list fills the tab; the right pane is hidden."""
        self.query_one(FilterableList).display = True
        self.query_one('.right-pane').display = False

    def minimize_list(self) -> None:
        """Work mode: the right pane fills the tab; the entity list is hidden."""
        self.query_one(FilterableList).display = False
        self.query_one('.right-pane').display = True

    def focus_content(self) -> None:
        """Move focus onto the detail pane's primary widget (editor / interfaces tree).

        Called when re-entering a tab that already has a selection, so the content is
        ready to edit or navigate without a detour through the list. A tab with no such
        widget inherits this no-op.
        """

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
