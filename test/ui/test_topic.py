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

"""The topic entry over the live demo world, echoing and publishing.

/chatter opens in Echo (it has a publisher): space starts the echo (◉ in the tab, the top bar and
the Here column), enter freezes the values ("❄ FROZEN +N new since" rising as the clock moves),
enter on a field hides it, esc goes live. /inbox opens in Publish (nobody publishes it): edit the
message, space publishes it once, R types a new rate, r repeats ("N sent", ↻ everywhere), s stops,
:rate and u change and undo the rate, a bad rate shows its errline.
"""

import pytest
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]


async def test_echo_chatter():
    async with ui_session() as s:
        await s.keys('enter')  # /chatter is the first row of the list.
        assert s.where('layer', 'mode', 'path') == ('in', 'normal', ['tabs', '/chatter'])
        for expected in ('≋ TOPIC', '/chatter', 'std_msgs/msg/String', '1 pub · 0 sub', ' Echo ', ' Publish ',
                         '▶ Start echo space', 'LATEST MESSAGE  not echoing · space starts'):
            assert expected in s.text(), expected
        assert s.line_with('[x] data', '–') and 'enter into latest message' in s.footer()
        await s.shot('chatter-open', expect='≋ TOPIC /chatter std_msgs/msg/String "1 pub · 0 sub", the Echo / Publish '
                     'switch on Echo; a blue "▶ Start echo space" button, the keys "enter freezes the values · y copies '
                     '· e publish" on the right; LATEST MESSAGE (selected) "not echoing · space starts", row "[x] data –"')

        await s.keys('space')
        assert s.bridge.subscriptions.get('/chatter') and 'chatter 1' not in s.text()  # Only the clock moves it.
        await s.advance(3.0)
        assert s.line_with('[x] data', "'chatter 3'") and 'chatter 4' not in s.text()
        assert s.line_with('LATEST MESSAGE', '● live · enter freezes it', '3 received · 1.0 Hz')
        assert s.line_with('■ Stop echo space') and not s.line_with('■ Stop echo space', 'received')
        assert s.line_with('/chatter ◉') and s.line_with('≋ ◉ /chatter')  # The tab and the top bar.
        assert s.line_with('/chatter', '◉ echo started')
        shot = await s.shot('echo-live', expect='echo running: an orange "■ Stop echo space" on its own row; '
                            'LATEST MESSAGE "● live · enter freezes it" (green ● live) with "3 received · 1.0 Hz" at '
                            'the right of its title, and "[x] data \'chatter 3\'"; a cyan ◉ after /chatter in the tab, '
                            '"≋ ◉ /chatter" at the right of the top bar; ACTIVITY "◉ echo started"')
        # The shot records the keys and clock steps since the last one, and the nav model's state.
        assert shot['keys'] == ['enter', 'space', '+3s'] and shot['keys_since_last_shot'] == ['space', '+3s']
        assert shot['state']['path'] == ['tabs', '/chatter'] and shot['state']['tabs'] == ['/chatter']

        await s.keys('enter')
        await s.advance(2.0)
        assert s.where('layer', 'mode', 'path') == ('area', 'normal', ['tabs', '/chatter', 'latest message'])
        assert s.line_with('❄ FROZEN', '+2 new since', 'esc goes live · enter shows / hides a field')
        assert s.line_with('[x] data', "'chatter 3'") and 'esc go live' in s.footer()
        await s.advance(1.0)
        assert s.line_with('❄ FROZEN', '+3 new since') and s.line_with('[x] data', "'chatter 3'")
        await s.shot('echo-frozen', expect='inside LATEST MESSAGE (blue border): a yellow "❄ FROZEN" pill, "+3 new '
                     'since", "esc goes live · enter shows / hides a field"; data still \'chatter 3\' on the cursor row; '
                     'footer tabs › /chatter › latest message, "esc go live", "enter show / hide field"')

        await s.keys('enter')
        assert s.line_with('[ ] data', 'hidden')
        await s.shot('echo-hidden', expect='enter hid the field: the row reads "[ ] data  hidden" (dim); still frozen')

        await s.keys('enter', 'escape')
        assert s.where('layer', 'mode', 'path') == ('in', 'normal', ['tabs', '/chatter'])
        assert s.line_with('[x] data', "'chatter 6'") and s.line_with('LATEST MESSAGE', '● live')
        await s.shot('echo-live-again', expect='esc went live: LATEST MESSAGE (selected, white border) "● live", '
                     "data 'chatter 6', the panel live again")

        await s.keys('0')
        assert s.line_with('/chatter', 'std_msgs/msg/String', '◉ echoing open')
        await s.shot('home-echoing', expect='the ☰ list: the /chatter row says "◉ echoing" (cyan) and "open" in the '
                     'Here column; the top bar still shows "≋ ◉ /chatter"')

        await s.keys('1', 'space')
        assert s.line_with('▶ Start echo space') and not s.line_with('≋ ◉ /chatter')
        assert s.line_with('/chatter', '■ echo stopped') and not s.bridge.subscriptions
        await s.advance(1.0)
        assert 'chatter 7' not in s.text()  # Stopped: nothing new comes in.


async def test_publish_inbox():
    async with ui_session() as s:
        await s.keys('slash', *'inbox', 'enter')
        assert s.where('layer', 'mode', 'path') == ('in', 'normal', ['tabs', '/inbox'])
        for expected in ('0 pub · 1 sub', '▶ Publish once space', '↻ Repeat at 10 Hz r', 'default · R changes it',
                         '[ ] earlier messages', 'MESSAGE  i edit · p paste'):
            assert expected in s.text(), expected
        assert s.line_with("1  data: ''", '# string')
        await s.shot('publish-open', expect='/inbox in Publish (the switch on Publish), "0 pub · 1 sub"; buttons "▶ '
                     'Publish once space" (blue) and "↻ Repeat at 10 Hz r" (grey, 10 underlined), "default · R changes '
                     'it"; MESSAGE (selected) with "1  data: \'\'  # string"')

        await s.keys('enter', 'enter', *'hello', 'escape', 'space')
        assert s.line_with('/inbox', '✓ published · data: hello') and s.line_with('[ ] history (1)')
        await s.shot('published', expect="MESSAGE shows data: 'hello' and \"[ ] history (1)\"; ACTIVITY \"≋ /inbox ✓ "
                     'published · data: hello" in green')

        await s.keys('R')
        assert s.where('layer', 'mode', 'path') == ('edit', 'insert', ['tabs', '/inbox', 'repeat rate', 'editing'])
        assert s.line_with('Repeat at 10', 'type a rate · enter keeps · 0.1–100 Hz')
        await s.shot('rate-editing', expect='R: the rate in the Repeat button is an edit box with "10" and a cursor '
                     '(the first key replaces it), "type a rate · enter keeps · 0.1–100 Hz"; no panel highlighted; footer '
                     'INSERT tabs › /inbox › repeat rate › editing')

        await s.keys(*'500', 'enter')
        assert s.line_with('✗ rate must be 0.1–100 Hz, got "500"') and s.where('layer', 'mode', 'path')[0] == 'edit'
        await s.shot('rate-error', expect='still typing the rate (500): the red errline "✗ rate must be 0.1–100 Hz, '
                     'got "500"" under MESSAGE and the same line in ACTIVITY')

        await s.keys('backspace', 'backspace', 'backspace', '5', 'enter')
        assert s.line_with('↻ Repeat at 5 Hz r', 'your rate · R changes it') and s.where('layer', 'mode', 'path')[0] == 'area'
        await s.keys('r')
        await s.advance(2.0)
        assert s.line_with('■ Stop repeating at 5 Hz s', '10 sent')
        assert s.line_with('/inbox ↻') and s.line_with('≋ ↻ /inbox') and s.line_with('↻ repeating at 5 Hz')
        await s.shot('publish-repeating', expect='repeating: an orange "■ Stop repeating at 5 Hz s", "your rate · R '
                     'changes it" and "10 sent" in green; a green ↻ after /inbox in the tab and "≋ ↻ /inbox" in the top '
                     'bar; ACTIVITY "↻ repeating at 5 Hz"')

        await s.keys(':', *'rate 2', 'enter')
        assert s.line_with('■ Stop repeating at 2 Hz s') and s.line_with('↻ rate now 2 Hz')
        await s.keys('u')
        assert s.line_with('■ Stop repeating at 5 Hz s')

        await s.keys('0')
        assert s.line_with('/inbox', '↻ 5 Hz open')
        await s.shot('home-repeating', expect='the ☰ list: the /inbox row says "↻ 5 Hz" (green) and "open" in the Here '
                     'column; "≋ ↻ /inbox" in the top bar')

        await s.keys('1', 's')
        assert s.line_with('↻ Repeat at 5 Hz r')
        assert s.line_with('■ repeat stopped after') and not s.line_with('≋ ↻ /inbox')

        await s.keys('e')
        assert s.line_with('▶ Start echo space') and s.where('layer', 'mode', 'path')[2] == ['tabs', '/inbox']
        await s.keys('space')
        await s.advance(0.5)
        assert s.line_with('[x] data', 'waiting — nobody publishes this yet')
        await s.shot('echo-nobody', expect='/inbox in Echo, echoing: "[x] data  waiting — nobody publishes this yet"')


async def test_echo_a_nested_message():
    async with ui_session() as s:
        await s.keys('slash', *'locali', 'enter', 'space')
        await s.advance(1.0)
        for field in ('header', 'pose.pose.position', 'pose.pose.orientation', 'pose.covariance'):
            assert s.line_with(f'[x] {field}'), field
        assert s.line_with('header', 'frame_id: map')
        assert s.line_with('pose.pose.position', '{x: 1.0806, y: 1.68294, z: 0.0}')  # Readable floats.
        await s.shot('echo-pose', expect='/localisation_pose echoing: one row per field, nested messages opened down to '
                     'their compact parts: header {stamp: …, frame_id: map}, pose.pose.position {x: 1.0806, …} '
                     '(floats cut to 6 significant digits), '
                     'pose.pose.orientation {x: …, w: …}, pose.covariance [0.0, …] cut at the panel edge')


async def test_closing_an_echoing_tab_stops_it():
    """x on a tab stops its echo: nothing would be left to stop it from. u reopens it, stopped."""
    async with ui_session() as s:
        await s.keys('enter', 'space')
        await s.advance(2.0)
        assert '◉ /chatter' in s.lines()[0]
        await s.keys('x')
        top, rows = s.lines()[0], s.line_with('≋ /chatter', 'std_msgs/msg/String')
        assert '◉' not in top and '◉' not in rows and '/chatter' not in s.bridge.subscriptions
        assert tuple(s.state()['log']) == ('x', 'closed /chatter — echo stopped · u reopens it')
        assert s.line_with('/chatter', '■ echo stopped')
        await s.shot('closed-echo-stopped', expect='the ☰ list after x on the echoing /chatter tab: no "◉ /chatter" '
                     'in the top bar, the /chatter row\'s Here column empty; the activity strip "■ echo stopped"; '
                     'the info toast "closed /chatter · u undoes"')
        await s.keys('u')
        assert s.state()['tabs'] == ['/chatter'] and s.line_with('▶ Start echo space')
