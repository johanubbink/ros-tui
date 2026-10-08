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

"""Clicking: tabs and their ×, the kind chips, list rows, panels,
the Echo / Publish switch, the buttons and the rate, the search box and its veil, search matches,
activity lines and :log lines. Each click does what its keys would; the log reads "click".
"""

import pytest
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]


async def test_click_through_the_shell():
    async with ui_session() as s:
        await s.click_on('Services 2')
        assert s.state()['chip'] == 1 and '⇄ SERVICES · 2' in s.text() and 'TOPICS ·' not in s.text()
        assert s.state()['log'] == ('click', 'showing services')
        await s.shot('chip-clicked', expect='the Services chip is filled and the list shows only the two services')
        await s.click_on('All 11')
        assert s.state()['chip'] == -1

        await s.click_on('/chatter')
        state = s.state()
        assert (state['layer'], state['tabs'], state['active']) == ('in', ['/chatter'], 0)
        assert s.state()['log'] == ('click', 'opened /chatter (tab 1)')

        await s.click_on('▶ Start echo')
        await s.advance(2.0)
        assert '◉' in s.text() and 'received · 1.0 Hz' in s.text()
        await s.shot('echo-started-by-click', expect='the Stop echo button after a click on Start echo; LATEST '
                     'MESSAGE says ● live with "2 received · 1.0 Hz" at the right of its title')

        await s.click_on('LATEST MESSAGE')
        assert (s.state()['layer'], s.state()['area']) == ('area', 'out')
        assert '❄ FROZEN' in s.text()
        await s.shot('area-clicked', expect='a click on LATEST MESSAGE went inside it: blue border, ❄ FROZEN')

        await s.click_on('☰ All')
        assert s.state()['active'] == -1 and s.state()['layer'] == 'in'
        await s.click_on('/chatter ◉', row=1)
        assert s.state()['active'] == 0

        await s.click_on('×', row=1)
        assert s.state()['tabs'] == [] and '◉' not in s.lines()[0]  # Nothing runs in the top bar.
        assert s.state()['log'] == ('click', 'closed /chatter — echo stopped · u reopens it')

        # The activity strip: a click on a line goes to its entry.
        await s.click_on('■ echo stopped')
        assert s.state()['tabs'] == ['/chatter'] and s.state()['active'] == 0
        await s.shot('activity-line-clicked', expect='a click on the "■ echo stopped" activity line opened '
                     '/chatter again as tab 1')


async def test_click_the_publish_buttons():
    async with ui_session() as s:
        await s.click_on('/inbox')
        await s.click_on('Echo')
        assert s.state()['entry_mode'] == 'echo'
        await s.click_on('Publish')
        assert s.state()['entry_mode'] == 'publish'

        await s.click_on('↻ Repeat at')
        assert '■ Stop repeating at 10 Hz s' in s.text()
        await s.shot('repeat-clicked', expect='a click on Repeat started it: "■ Stop repeating at 10 Hz s", ↻ in the tab')
        await s.click_on('■ Stop repeating')
        assert '↻ Repeat at 10 Hz r' in s.text() and s.state()['log'][0] == 'click'

        await s.click_on('10 Hz')  # The rate, inside the Repeat button.
        assert s.state()['layer'] == 'edit' and s.state()['path'][-2:] == ['repeat rate', 'editing']
        await s.keys('backspace', 'backspace', '5')
        await s.click_on('▶ Publish once')  # Keeps the typed rate first, then publishes, as ^s does.
        assert s.state()['layer'] == 'in' and '↻ Repeat at 5 Hz r' in s.text()
        assert [name for name, *_ in s.bridge.published] == ['/inbox']
        assert s.bridge.periodic_started == [('/inbox', 10.0)]


async def test_click_into_another_area_keeps_the_edit():
    async with ui_session() as s:
        await s.keys('slash', *'add', 'enter')
        await s.keys('enter', 'i', '7')
        assert s.state()['layer'] == 'edit'
        await s.click_on('RESPONSE')
        state = s.state()
        assert (state['layer'], state['area']) == ('area', 'out')
        assert 'a: 7' in s.text()
        await s.shot('edit-kept-by-click', expect='a click on RESPONSE kept a: 7 (as esc would) and went inside '
                     'RESPONSE: its border is blue, REQUEST at rest')


async def test_click_search_and_log():
    async with ui_session() as s:
        await s.click_on('/ search everything')
        assert s.state()['search'] == ''
        await s.click(60, 30)  # The veil: anywhere outside the popup.
        assert s.state()['search'] is None
        assert s.state()['log'] == ('esc', 'search closed — back where you were')

        await s.keys('colon', 'l')
        await s.click_on(':l')  # The command line is that popup: a click on it keeps it open.
        assert s.state()['overlay'] == 'CommandLine'
        await s.click(60, 20)
        assert s.state()['overlay'] is None

        await s.click_on('/ search everything')
        await s.type_text('add')
        await s.shot('search-to-click', expect='search for "add" with /add_two_ints as the only match')
        await s.click_on('/add_two_ints  AddTwoInts')  # The match, not the list row under the veil.
        assert s.state()['search'] is None and s.state()['tabs'] == ['/add_two_ints']

        await s.keys('space')
        await s.advance(0.2)
        await s.keys('0', 'colon', *'log', 'enter')
        assert s.state()['overlay'] == 'LogView'
        await s.shot('log-to-click', expect=':log lists the call and its response; a click on a line goes there')
        await s.click_on('▶ called')
        assert s.state()['overlay'] is None and s.state()['active'] == 0
