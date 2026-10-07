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

"""The topic entry over the live demo world, following the design's try-steps 1–4.

/chatter opens in Echo (it has a publisher): space starts the echo (◉ in the tab, the top bar and
the Here column), enter freezes the values ("❄ FROZEN +N new since" rising as the clock moves),
enter on a field hides it, esc goes live. /inbox opens in Publish (nobody publishes it): edit the
message, space publishes it once, R types a new rate, r repeats ("N sent", ↻ everywhere), s stops,
:rate and u change and undo the rate, a bad rate shows its errline. Design references: chatter-open,
echo-live, echo-frozen, publish-open, publish-repeating, rate-editing (docs/design/reference_shots.json).
"""

import pytest
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]


def footer(s) -> str:
    return s.text().splitlines()[-1]


def line_with(s, *parts) -> str:
    """The first screen line holding all of `parts` ('' if none)."""
    return next((line for line in s.text().splitlines() if all(part in line for part in parts)), '')


def where(s) -> tuple:
    state = s.state()
    return state['layer'], state['mode'], state['path']


async def test_echo_chatter():
    async with ui_session() as s:
        await s.keys('enter')  # /chatter is the first row of the list.
        assert where(s) == ('in', 'normal', ['tabs', '/chatter'])
        for expected in ('≋ TOPIC', '/chatter', 'std_msgs/msg/String', '1 pub · 0 sub', ' Echo ', ' Publish ',
                         '▶ Start echo space', 'LATEST MESSAGE  not echoing · space starts'):
            assert expected in s.text(), expected
        assert line_with(s, '[x] data', '–') and 'enter into latest message' in footer(s)
        await s.shot('chatter-open', expect='≋ TOPIC /chatter std_msgs/msg/String "1 pub · 0 sub", the Echo / Publish '
                     'switch on Echo; a blue "▶ Start echo space" button, the keys "enter freezes the values · y copies '
                     '· e publish" on the right; LATEST MESSAGE (selected) "not echoing · space starts", row "[x] data –"')

        await s.keys('space')
        await s.advance(3.0)
        assert line_with(s, '[x] data', "'chatter 3'")
        assert line_with(s, 'LATEST MESSAGE', '● live · enter freezes it', '3 received · 1.0 Hz')
        assert line_with(s, '■ Stop echo space') and not line_with(s, '■ Stop echo space', 'received')
        assert line_with(s, '/chatter ◉') and line_with(s, '≋ ◉ /chatter')  # The tab and the top bar.
        assert line_with(s, '/chatter', '◉ echo started')
        await s.shot('echo-live', expect='echo running: an orange "■ Stop echo space" on its own row; LATEST MESSAGE '
                     '"● live · enter freezes it" (green ● live) with "3 received · 1.0 Hz" at the right of its title, '
                     'and "[x] data \'chatter 3\'"; a cyan ◉ '
                     'after /chatter in the tab, "≋ ◉ /chatter" at the right of the top bar; ACTIVITY "◉ echo started"')

        await s.keys('enter')
        await s.advance(2.0)
        assert where(s) == ('area', 'normal', ['tabs', '/chatter', 'latest message'])
        assert line_with(s, '❄ FROZEN', '+2 new since', 'esc goes live · enter shows / hides a field')
        assert line_with(s, '[x] data', "'chatter 3'") and 'esc go live' in footer(s)
        await s.advance(1.0)
        assert line_with(s, '❄ FROZEN', '+3 new since') and line_with(s, '[x] data', "'chatter 3'")
        await s.shot('echo-frozen', expect='inside LATEST MESSAGE (blue border): a yellow "❄ FROZEN" pill, "+3 new '
                     'since", "esc goes live · enter shows / hides a field"; data still \'chatter 3\' on the cursor row; '
                     'footer tabs › /chatter › latest message, "esc go live", "enter show / hide field"')

        await s.keys('enter')
        assert line_with(s, '[ ] data', 'hidden')
        await s.shot('echo-hidden', expect='enter hid the field: the row reads "[ ] data  hidden" (dim); still frozen')

        await s.keys('enter', 'escape')
        assert where(s) == ('in', 'normal', ['tabs', '/chatter'])
        assert line_with(s, '[x] data', "'chatter 6'") and line_with(s, 'LATEST MESSAGE', '● live')
        await s.shot('echo-live-again', expect='esc went live: LATEST MESSAGE (selected, white border) "● live", '
                     "data 'chatter 6', the panel no longer frozen")

        await s.keys('0')
        assert line_with(s, '/chatter', 'std_msgs/msg/String', '◉ echoing open')
        await s.shot('home-echoing', expect='the ☰ list: the /chatter row says "◉ echoing" (cyan) and "open" in the '
                     'Here column; the top bar still shows "≋ ◉ /chatter"')

        await s.keys('1', 'space')
        assert line_with(s, '▶ Start echo space') and not line_with(s, '≋ ◉ /chatter')
        assert line_with(s, '/chatter', '■ echo stopped')


async def test_publish_inbox():
    async with ui_session() as s:
        await s.keys('slash', *'inbox', 'enter')
        assert where(s) == ('in', 'normal', ['tabs', '/inbox'])
        for expected in ('0 pub · 1 sub', '▶ Publish once space', '↻ Repeat at 10 Hz r', 'default · R changes it',
                         '[ ] earlier messages', 'MESSAGE  i edit · p paste'):
            assert expected in s.text(), expected
        assert line_with(s, "1  data: ''", '# string')
        await s.shot('publish-open', expect='/inbox in Publish (the switch on Publish), "0 pub · 1 sub"; buttons "▶ '
                     'Publish once space" (blue) and "↻ Repeat at 10 Hz r" (grey, 10 underlined), "default · R changes '
                     'it"; MESSAGE (selected) with "1  data: \'\'  # string"')

        await s.keys('enter', 'enter', *'hello', 'escape', 'space')
        assert s.bridge.published[-1][2].data == 'hello'
        assert line_with(s, '/inbox', '✓ published · data: hello') and line_with(s, '[ ] history (1)')
        await s.shot('published', expect="MESSAGE shows data: 'hello' and \"[ ] history (1)\"; ACTIVITY \"≋ /inbox ✓ "
                     'published · data: hello" in green')

        await s.keys('R')
        assert where(s) == ('edit', 'insert', ['tabs', '/inbox', 'repeat rate', 'editing'])
        assert line_with(s, 'Repeat at 10', 'type a rate · enter keeps · 0.1–100 Hz')
        await s.shot('rate-editing', expect='R: the rate in the Repeat button is an edit box with "10" and a cursor '
                     '(the first key replaces it), "type a rate · enter keeps · 0.1–100 Hz"; no panel highlighted; footer '
                     'INSERT tabs › /inbox › repeat rate › editing')

        await s.keys(*'500', 'enter')
        assert line_with(s, '✗ rate must be 0.1–100 Hz, got "500"') and where(s)[0] == 'edit'
        await s.shot('rate-error', expect='still typing the rate (500): the red errline "✗ rate must be 0.1–100 Hz, '
                     'got "500"" under MESSAGE and the same line in ACTIVITY')

        await s.keys('backspace', 'backspace', 'backspace', '5', 'enter')
        assert line_with(s, '↻ Repeat at 5 Hz r', 'your rate · R changes it') and where(s)[0] == 'area'
        await s.keys('r')
        await s.advance(2.0)
        assert s.bridge.periodic_started == [('/inbox', 5.0)]
        assert line_with(s, '■ Stop repeating at 5 Hz s', '10 sent')
        assert line_with(s, '/inbox ↻') and line_with(s, '≋ ↻ /inbox') and line_with(s, '↻ repeating at 5 Hz')
        await s.shot('publish-repeating', expect='repeating: an orange "■ Stop repeating at 5 Hz s", "your rate · R '
                     'changes it" and "10 sent" in green; a green ↻ after /inbox in the tab and "≋ ↻ /inbox" in the top '
                     'bar; ACTIVITY "↻ repeating at 5 Hz"')

        await s.keys(':', *'rate 2', 'enter')
        assert s.bridge.periodic_started[-1] == ('/inbox', 2.0)
        assert line_with(s, '■ Stop repeating at 2 Hz s') and line_with(s, '↻ rate now 2 Hz')
        await s.keys('u')
        assert line_with(s, '■ Stop repeating at 5 Hz s') and s.bridge.periodic_started[-1] == ('/inbox', 5.0)

        await s.keys('0')
        assert line_with(s, '/inbox', '↻ 5 Hz open')
        await s.shot('home-repeating', expect='the ☰ list: the /inbox row says "↻ 5 Hz" (green) and "open" in the Here '
                     'column; "≋ ↻ /inbox" in the top bar')

        await s.keys('1', 's')
        assert s.bridge.periodic_stopped == ['/inbox'] and line_with(s, '↻ Repeat at 5 Hz r')
        assert line_with(s, '■ repeat stopped after') and not line_with(s, '≋ ↻ /inbox')

        await s.keys('e')
        assert line_with(s, '▶ Start echo space') and where(s)[2] == ['tabs', '/inbox']
        await s.keys('space')
        await s.advance(0.5)
        assert line_with(s, '[x] data', 'waiting — nobody publishes this yet')
        await s.shot('echo-nobody', expect='/inbox in Echo, echoing: "[x] data  waiting — nobody publishes this yet"')


async def test_echo_a_nested_message():
    async with ui_session() as s:
        await s.keys('slash', *'locali', 'enter', 'space')
        await s.advance(1.0)
        for field in ('header', 'pose.pose.position', 'pose.pose.orientation', 'pose.covariance'):
            assert line_with(s, f'[x] {field}'), field
        assert line_with(s, 'header', 'frame_id: map')
        assert line_with(s, 'pose.pose.position', '{x: 1.0806, y: 1.68294, z: 0.0}')  # Readable floats.
        await s.shot('echo-pose', expect='/localisation_pose echoing: one row per field, nested messages opened down to '
                     'their compact parts: header {stamp: …, frame_id: map}, pose.pose.position {x: 1.0806, …} '
                     '(floats cut to 6 significant digits), '
                     'pose.pose.orientation {x: …, w: …}, pose.covariance [0.0, …] cut at the panel edge')


async def test_closing_an_echoing_tab_stops_it():
    """x on a tab stops its echo: nothing would be left to stop it from. u reopens it, stopped."""
    async with ui_session() as s:
        await s.keys('enter', 'space')
        await s.advance(2.0)
        assert '◉ /chatter' in s.text().splitlines()[0]
        await s.keys('x')
        top, rows = s.text().splitlines()[0], line_with(s, '≋ /chatter', 'std_msgs/msg/String')
        assert '◉' not in top and '◉' not in rows and '/chatter' not in s.bridge.subscriptions
        assert tuple(s.state()['log']) == ('x', 'closed /chatter — echo stopped · u reopens it')
        assert line_with(s, '/chatter', '■ echo stopped')
        await s.shot('closed-echo-stopped', expect='the ☰ list after x on the echoing /chatter tab: no "◉ /chatter" '
                     'in the top bar, the /chatter row\'s Here column empty; the activity strip "■ echo stopped"; '
                     'the info toast "closed /chatter · u undoes"')
        await s.keys('u')
        assert s.state()['tabs'] == ['/chatter'] and line_with(s, '▶ Start echo space')
