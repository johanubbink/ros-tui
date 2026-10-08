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

"""A small fixed world for the pure nav-model tests (test_nav.py, test_keymap.py).

``FIXTURE_CATALOG`` lists a few entries of every kind. ``FixtureEntry`` is the base ``Entry``
with the areas (and a topic's Echo / Publish modes) of the real kind. ``RowsEntry`` adds three
editable number rows per editable area, so the AREA and EDIT layers and per-tab undo are tested
without the real entries; ``RowsWorld`` makes them and records the verbs they run.
"""

from types import SimpleNamespace

from ros_tui.ui.entries.base import Commit, Editing, Entry, UndoEntry
from ros_tui.ui.entries.kinds import KINDS
from ros_tui.ui.catalog import CatalogItem
from ros_tui.ui.nav import NavState

FIXTURE_CATALOG = SimpleNamespace(
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


class FixtureEntry(Entry):
    """No rows and no verbs, but the real kind's areas, and a topic opens in Echo when someone
    publishes it, else in Publish, as in TopicEntry."""

    def __init__(self, tab, ctx=None):
        super().__init__(tab, ctx)
        self.AREAS, self.MODES = KINDS[tab.kind].AREAS, KINDS[tab.kind].MODES

    def on_open(self, nav):
        if self.MODES and not self.mode:
            self.mode = 'echo' if nav.catalog.item(self.tab).publishers > 0 else 'publish'

    def label_vars(self):
        return {'rate': '10'} if self.MODES else {}


class RowsEntry(FixtureEntry):
    """Every area has three rows; editable ones hold numbers a, b, c (1, 2, 3). Row c of a message
    has a Quaternion helper, enter on an interface row opens /chatter, and verbs are recorded."""

    VERBS = ('primary', 'secondary', 'repeat', 'rate', 'set_rate', 'helper', 'helper_apply', 'history_older',
             'history_newer', 'yank', 'paste', 'fold', 'unfold', 'add_item', 'delete_item')

    def __init__(self, tab, record):
        super().__init__(tab)
        self.values: dict[str, list[str]] = {}  # Area id -> its values.
        self.record = record

    def row_count(self, area):
        return len(FIELDS)

    def start_edit(self, area, row, clear):
        if not area.editable:
            return None
        value = self.values.setdefault(area.id, ['1', '2', '3'])[row]
        return Editing(area.id, row, '' if clear else value, old=value, field=FIELDS[row])

    def commit_edit(self, editing):
        value = editing.value.strip()
        try:
            float(value)
        except ValueError:
            return Commit(False, f'{editing.field} needs a number, got "{value}"')
        values = self.values.setdefault(editing.area, ['1', '2', '3'])
        values[editing.row] = value
        changed = value != editing.old
        undo = UndoEntry(self.tab, lambda nav: self._undo(values, editing.row, editing.old)) if changed else None
        return Commit(True, f'kept {editing.field} = {value}' + (' (u undoes)' if changed else ''), undo)

    def _undo(self, values, row, old):
        values[row] = old
        return f'undid the edit of {FIELDS[row]} on {self.tab.name}'

    def activate_row(self, nav, area, row, how):
        if area.id != 'ifs':
            return False
        nav.open_entity('topics', '/chatter', how)
        return True

    def helper_name(self, area, row):
        return 'Quaternion' if row == 2 else None

    def verbs(self):
        return {name: lambda nav, how, arg, name=name: self.record.append((name, how, arg)) for name in self.VERBS}


class RowsWorld:
    """NavState's `new_entry` for RowsEntry: `verbs` records every verb any of them ran."""

    def __init__(self):
        self.verbs: list[tuple[str, str, object]] = []

    def __call__(self, tab):
        return RowsEntry(tab, self.verbs)


def fixture_nav(new_entry=FixtureEntry) -> NavState:
    nav = NavState(new_entry)
    nav.set_catalog(FIXTURE_CATALOG)
    return nav


def nav_after(keys, new_entry=FixtureEntry) -> NavState:
    """A fresh NavState over the fixture world after pressing `keys`."""
    nav = fixture_nav(new_entry)
    for key in keys:
        nav.handle_key(key)
    return nav
