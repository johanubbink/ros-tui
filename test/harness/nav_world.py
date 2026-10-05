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

"""The design prototype's world for the pure nav-model tests (test_nav.py, test_keymap.py).

``DESIGN_CATALOG`` is KINDS from docs/design/hybrid-keys.html. ``RowsProvider`` is a stand-in
``EntryProvider`` with three editable number rows per editable area, so the AREA and EDIT layers and
per-tab undo can be tested before the real entries exist.
"""

from types import SimpleNamespace

from ros_tui.ui.nav import CatalogItem, Commit, Editing, EntryProvider, NavState, UndoEntry

DESIGN_CATALOG = SimpleNamespace(
    topics=[CatalogItem('/chatter', 'std_msgs/msg/String', 1),
            CatalogItem('/counter', 'std_msgs/msg/Int32', 1),
            CatalogItem('/diagnostic_status', 'diagnostic_msgs/msg/DiagnosticStatus', 1),
            CatalogItem('/inbox', 'std_msgs/msg/String', 0),
            CatalogItem('/localisation_pose', 'geometry_msgs/msg/PoseWithCovarianceStamped', 1),
            CatalogItem('/goal_pose', 'geometry_msgs/msg/PoseStamped', 0)],
    services=[CatalogItem('/add_two_ints', 'example_interfaces/srv/AddTwoInts'),
              CatalogItem('/set_pose', 'example_interfaces/srv/SetPose')],
    actions=[CatalogItem('/fibonacci', 'example_interfaces/action/Fibonacci'),
             CatalogItem('/navigate_to_pose', 'nav2_msgs/action/NavigateToPose')],
    nodes=[CatalogItem('/ros_tui_demo_servers', 'namespace /'), CatalogItem('/talker', 'namespace /')],
)
FIELDS = ('a', 'b', 'c')


class RowsProvider(EntryProvider):
    """Every area has three rows; editable ones hold numbers a, b, c (1, 2, 3) per entry. Row c of a
    message has a Quaternion helper, enter on an interface row opens /chatter, and verbs are recorded."""

    def __init__(self):
        super().__init__()
        self.values: dict[str, list[str]] = {}
        self.verbs: list[tuple[str, str, object]] = []

    def row_count(self, tab, area):
        return len(FIELDS)

    def _values(self, tab, area):
        return self.values.setdefault(f'{tab.key}|{area.id}', ['1', '2', '3'])

    def start_edit(self, tab, area, row, clear):
        if not area.editable:
            return None
        value = self._values(tab, area)[row]
        return Editing(area.id, row, '' if clear else value, old=value, field=FIELDS[row])

    def commit_edit(self, tab, editing):
        value = editing.value.strip()
        try:
            float(value)
        except ValueError:
            return Commit(False, f'{editing.field} needs a number, got "{value}"')
        area = next(a for a in self.areas(tab) if a.id == editing.area)
        self._values(tab, area)[editing.row] = value
        changed = value != editing.old
        undo = UndoEntry(tab.key, 'edit', (area, editing.row, editing.old)) if changed else None
        return Commit(True, f'kept {editing.field} = {value}' + (' (u undoes)' if changed else ''), undo)

    def undo(self, nav, entry):
        area, row, old = entry.data
        tab = next(t for t in nav.tabs if t.key == entry.owner)
        self._values(tab, area)[row] = old
        return f'undid the edit of {FIELDS[row]} on {tab.name}'

    def activate_row(self, nav, tab, area, row, how):
        if area.id != 'ifs':
            return False
        nav.open_entity('topics', '/chatter', how)
        return True

    def helper_name(self, tab, area, row):
        return 'Quaternion' if row == 2 else None

    def verb(self, nav, tab, name, how, arg=None):
        if name == 'toggle_mode':
            return super().verb(nav, tab, name, how, arg)
        self.verbs.append((name, how, arg))
        return True


def design_nav(provider=None) -> NavState:
    nav = NavState(provider=provider or EntryProvider())
    nav.set_catalog(DESIGN_CATALOG)
    return nav


def nav_after(keys, provider=None) -> NavState:
    """A fresh NavState over the design's world after pressing `keys`."""
    nav = design_nav(provider)
    for key in keys:
        nav.handle_key(key)
    return nav
