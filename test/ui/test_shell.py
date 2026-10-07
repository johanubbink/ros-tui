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

"""The app shell over the live demo world.

The ☰ list with its chips, opening entries as tabs,
the tab-row layer, the overflow of many tabs, closing and reopening a tab, and H / L. Design
references: home, topic-chip, chatter-open, tab-row, many-tabs (docs/design/reference_shots.json).
"""

import pytest
from harness.fake_bridge import FakeBridge
from harness.screens import ui_session
from ros_tui.ros.graph import GraphSnapshot, InterfaceEntry
from ros_tui.ui.widgets.tab_row import fit_tabs

pytestmark = [pytest.mark.ui, pytest.mark.shots]

TEN_TABS = ['/chatter', '/counter', '/diagnostic_status', '/inbox', '/localisation_pose', '/goal_pose',
            '/add_two_ints', '/set_pose', '/fibonacci', '/ros_tui_demo_servers']


def footer(s) -> str:
    return s.text().splitlines()[-1]


async def test_shell():
    async with ui_session() as s:
        state = s.state()
        assert (state['layer'], state['mode'], state['path']) == ('in', 'normal', ['tabs', '☰ list'])
        text = s.text()
        for expected in ('ros_tui', '/ search everything', '0 ☰ All', 'All 11', '≋ Topics 6', '⇄ Services 2',
                         '≋ TOPICS · 6', '⇄ SERVICES · 2', '▷ ACTIONS · 1', '◆ NODES · 2', 'namespace /',
                         'ACTIVITY · ALL TABS', 'nothing yet — what you send shows up here'):
            assert expected in text, expected
        assert ' NORMAL ' in footer(s) and 'tabs › ☰ list' in footer(s)
        assert 'esc tab row' in footer(s) and 'enter open /chatter' in footer(s) and '? keys' in footer(s)
        await s.shot('home', expect='☰ All list: chips "All 11 · ≋ Topics 6 · ⇄ Services 2 · ▷ Actions 1 · ◆ Nodes 2", '
                     'rows grouped under ≋ TOPICS · 6 … ◆ NODES · 2 with Name / Type / Here, the cursor bar on '
                     '/chatter; footer NORMAL tabs › ☰ list, esc tab row, enter open /chatter')

        await s.keys('tab')
        assert s.state()['chip'] == 0
        text = s.text()
        assert '0 ☰ Topics' in text and '≋ TOPICS · 6' in text and 'SERVICES ·' not in text
        await s.shot('topic-chip', expect='the Topics chip is on and the ☰ tab reads "☰ Topics"; only the six '
                     'topics are listed')

        await s.keys('shift+tab')
        assert s.state()['chip'] == -1 and '0 ☰ All' in s.text()

        await s.keys('enter')
        state = s.state()
        assert state['tabs'] == ['/chatter'] and state['active'] == 0 and state['path'] == ['tabs', '/chatter']
        text = s.text()
        assert '≋ TOPIC' in text and 'std_msgs/msg/String' in text and 'LATEST MESSAGE' in text
        assert ' Echo ' in text  # /chatter has a publisher, so it opens in Echo.
        assert 'enter into latest message' in footer(s)
        await s.shot('chatter-open', expect='tab 1 "≋ /chatter ×" active and underlined in the topic tint; '
                     'header ≋ TOPIC /chatter std_msgs/msg/String with Echo on; the LATEST MESSAGE panel has a '
                     'white (selected) border; footer tabs › /chatter, enter into latest message')

        await s.keys('enter')
        assert s.state()['layer'] == 'area'
        assert 'tabs › /chatter › latest message' in footer(s) and 'esc back out' in footer(s)
        await s.shot('inside-area', expect='the LATEST MESSAGE panel border is blue (inside the area); footer '
                     'tabs › /chatter › latest message, esc back out')

        await s.keys('escape', 'escape')
        state = s.state()
        assert (state['layer'], state['tab_cur'], state['path']) == ('tabs', 0, ['tabs'])
        assert 'esc' not in footer(s) and 'enter go in' in footer(s)
        await s.shot('tab-row', expect='the tab-row layer: tab 1 /chatter outlined by the cursor; footer just '
                     '"tabs", enter go in, no esc label')

        await s.keys('h')
        assert s.state()['tab_cur'] == -1
        await s.shot('tab-row-home', expect='the tab-row cursor on "0 ☰ All"; /chatter stays the active tab')
        await s.keys('l')
        assert s.state()['tab_cur'] == 0

        await s.keys('0')
        state = s.state()
        assert (state['layer'], state['active'], state['list_cur']) == ('in', -1, 0)
        assert 'open' in next(line for line in s.text().splitlines() if '/chatter' in line and 'String' in line)

        for _ in TEN_TABS[1:]:
            await s.keys('j', 'enter', '0')
        await s.keys('enter')  # The cursor is on the tenth entry, already open: go to its tab.
        state = s.state()
        assert state['tabs'] == TEN_TABS and state['active'] == 9
        text = s.text()
        assert 'more ›' not in text.splitlines()[1] and '‹ ' in text.splitlines()[1]
        assert '/ros_tui_demo_servers' in text.splitlines()[1]
        await s.shot('many-tabs', expect='10 tabs open: the row scrolled to keep tab 10 /ros_tui_demo_servers '
                     '(◆, no number) in view, "‹ N more" on the left')

        await s.keys('escape', 'g', 'g')
        state = s.state()
        assert (state['layer'], state['tab_cur']) == ('tabs', -1)
        row = s.text().splitlines()[1]
        assert '0 ☰ All' in row and 'more ›' in row and '‹' not in row
        await s.shot('many-tabs-start', expect='tab-row layer with the cursor on ☰: the row scrolled back to the '
                     'start, "N more ›" on the right; tab 10 stays active')

        await s.keys('enter', 'x')
        state = s.state()
        assert len(state['tabs']) == 10 and state['active'] == -1  # x on ☰: the list always stays.
        await s.keys('2', 'x')
        state = s.state()
        assert '/counter' not in state['tabs'] and len(state['tabs']) == 9 and state['active'] == 1
        assert state['toast'] == ['closed /counter · u undoes', 'info']
        await s.shot('closed', expect='/counter closed: 9 tabs, tab 2 is now /diagnostic_status')
        await s.keys('u')
        state = s.state()
        assert state['tabs'] == TEN_TABS and state['active'] == 1
        await s.shot('reopened', expect='u reopened /counter as tab 2, active again')

        await s.keys('H')
        assert s.state()['active'] == 0
        await s.keys('H')
        assert s.state()['active'] == -1 and s.state()['path'] == ['tabs', '☰ list']
        await s.keys('H')
        assert s.state()['active'] == 9  # H wraps from ☰ to the last tab.
        await s.keys('L', 'L')
        assert s.state()['active'] == 0
        await s.shot('h-l', expect='after H H H L L: tab 1 /chatter active, the row scrolled back to the start')


async def test_quit_and_textual_keys():
    """tab never moves focus (it's the chip filter), ctrl+p isn't the command palette, the overlay and
    send keys reach the nav model, :q quits."""
    async with ui_session() as s:
        assert s.app.focused is None
        await s.keys('tab', 'ctrl+p')
        assert s.app.focused is None and s.state()['chip'] == 0 and len(s.app.screen_stack) == 1
        await s.keys('enter')  # Open /chatter: space and ctrl+s are its primary verb.
        for key, logged in (('space', 'space'), ('ctrl+s', '^s')):
            await s.keys(key)
            assert s.state()['log'][0] == logged, key
        await s.keys('/', 'c')
        assert (s.state()['search'], s.state()['mode']) == ('c', 'search')
        await s.keys('escape', '?')
        assert s.state()['search'] is None and s.state()['which_key'] == 'all'
        await s.keys('x', ':', 'q')
        assert s.state()['which_key'] is None and s.state()['cmd'] == 'q'
        await s.keys('enter')
        assert s.app.return_code == 0 and not s.app.is_running


async def test_graph_updates_and_publishers():
    """The ☰ list follows the graph; a topic without publishers opens in Publish."""
    bridge = FakeBridge.demo()
    async with ui_session(bridge=bridge) as s:
        assert '/inbox' in s.text()
        bridge.listener(GraphSnapshot(2, actions=(), services=(), nodes=(),
                                      topics=(InterfaceEntry('/inbox', ('std_msgs/msg/String',)),)))
        await s.idle()
        assert '/chatter' not in s.text() and 'All 1' in s.text()
        await s.keys('enter')
        assert 'MESSAGE' in s.text() and 'LATEST MESSAGE' not in s.text()


@pytest.mark.parametrize('widths, want, start, room, shown', [
    ([10] * 5, 0, 0, 100, (0, 5)),  # everything fits
    ([10] * 20, 0, 0, 60, (0, 5)),  # 6 fit, one gives way to "N more ›"
    ([10] * 20, 19, 0, 60, (15, 20)),  # the last tab: "‹ N more" only
    ([10] * 20, 10, 15, 60, (10, 14)),  # moving left: the wanted tab becomes the first shown
    ([10] * 20, 12, 10, 60, (10, 14)),  # still in view: no scroll
])
def test_fit_tabs(widths, want, start, room, shown):
    assert fit_tabs(widths, want, start, room) == shown


async def test_narrow_terminal():
    """At 83 columns the hints on the right give way, so the chips and the buttons stay whole."""
    async with ui_session(size=(83, 35)) as s:
        lines = s.text().splitlines()
        assert 'Nodes 2' in lines[3]
        assert lines[-3].rstrip().endswith(':log for everything · click a line to go there')
        await s.shot('narrow-home', expect='at 83x35 all five kind chips show whole')
        await s.keys('enter', 'space', 'e', 'r')
        lines = s.text().splitlines()
        assert 'other tabs dimmed' in lines[-4] and lines[-4].rstrip().endswith('   :log for everything')
        assert 'Stop repeating at 10 Hz s   default · R changes it' in lines[5] and 'earlier' not in lines[5]
        await s.shot('narrow-publish', expect='/chatter repeating at 83x35: both buttons and "default · R changes '
                     'it" show (the sent count is cut at the edge) and "[ ] earlier messages" is dropped; the '
                     'activity head keeps "other tabs dimmed" and shortens its right side to ":log for everything"')
