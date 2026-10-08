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

"""The action entry over the live demo world, plus /turtle1/rotate_absolute (rotate_demo()).

/fibonacci: edit the order, space sends the goal (EXECUTING, the feedback sequence growing as the
clock moves, the ◐◓◑◒ spinner in the tab, the top bar and the Here column), a second goal is blocked
on another action and on the same one, s cancels (CANCELED with the last feedback), a goal that
succeeds and one that aborts. u with nothing to undo says "nothing to undo here", a goal keeps
running when its tab closes (u reopens it), and a long result wraps.
"""

import pytest
from harness.fake_bridge import ROTATE_ACTION, rotate_demo
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]

FIB = '/fibonacci'
ROTATE = ROTATE_ACTION.name


async def test_action_entry():
    async with ui_session(bridge=rotate_demo()) as s:
        await s.keys('slash', *'fib', 'enter')
        assert s.state()['path'] == ['tabs', FIB]
        for expected in ('▷ ACTION', 'example_interfaces/action/Fibonacci', '▶ Send goal space', '■ Cancel goal s',
                         '[ ] earlier goals', 'RESULT  no goal yet'):
            assert expected in s.text(), expected
        assert s.line_with('1  order: 0', '# int32') and 'enter into goal' in s.footer()
        await s.shot('action-open', expect='▷ ACTION /fibonacci example_interfaces/action/Fibonacci; a blue "▶ Send '
                     'goal space" and a dim, disabled "■ Cancel goal s"; GOAL (selected, two thirds of the width) with '
                     '"1  order: 0  # int32"; RESULT "no goal yet"')

        await s.keys('enter', 'enter', '1', '2', 'escape', 'space')
        assert s.line_with(FIB, '▶ goal sent · order: 12')
        await s.advance(0.9)
        assert s.line_with('RESULT', 'EXECUTING', '0.9 s · live feedback')
        assert s.line_with('sequence: [0, 1, 1, 2, 3]')
        assert s.line_with('ros_tui', '▷ ◒ /fibonacci')  # The top bar's running list; the frame at 0.9 s.
        assert s.line_with('1 ▷ /fibonacci ◒')  # The tab.
        await s.shot('action-executing', expect='space sent the goal: a dim, disabled "▶ Send goal space" and an '
                     'orange "■ Cancel goal s"; RESULT has a cyan EXECUTING pill, "0.9 s · live feedback" and '
                     '"sequence: [0, 1, 1, 2, 3]"; a cyan spinner ◒ after /fibonacci in the tab and "▷ ◒ /fibonacci" in '
                     'the top bar; ACTIVITY "▷ /fibonacci ▶ goal sent · order: 12"')
        await s.advance(1.5)
        assert s.line_with('EXECUTING', '2.4 s · live feedback')
        assert s.line_with('sequence: [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]')
        await s.shot('action-feedback-grows', expect='1.5 s later the RESULT shows "2.4 s · live feedback" and the '
                     'sequence grew to [0, 1, 1, 2, 3, 5, 8, 13, 21, 34], wrapped if it is too wide; the spinner is on '
                     'another frame (◓)')

        await s.keys('0')
        assert s.line_with(FIB, '◓ running', 'open')
        await s.shot('home-running', expect='the ☰ list: the /fibonacci row says "◓ running open" in its Here column, '
                     'and the top bar still shows "▷ ◓ /fibonacci"')

        await s.keys('slash', *'rotate', 'enter', 'space')
        assert s.state()['tabs'] == [FIB, ROTATE]
        assert s.line_with('✗ a goal is already running on /fibonacci') and '— s cancels it' not in s.text()
        assert s.line_with('▶ Send goal space', 'a goal is running on /fibonacci', '■ Cancel goal s')
        assert s.line_with('▷ /turtle1/rotate_abso', '✗ a goal is already running on /fibonacci')  # ACTIVITY.
        await s.shot('action-blocked', expect='on /turtle1/rotate_absolute space sent nothing: "▶ Send goal space" is '
                     'dim, "a goal is running on /fibonacci" follows it, the Cancel button is dim too; the GOAL panel '
                     'ends with the red errline "✗ a goal is already running on /fibonacci", and ACTIVITY has the same '
                     'line in red; theta: 0.0 in GOAL')
        await s.keys('u')
        assert s.state()['toast'] == ['nothing to undo here', 'info']
        await s.shot('undo-nothing', expect='u on the rotate tab, which has no change of its own: the blue toast '
                     '"nothing to undo here", bottom right; nothing else changed')

        await s.keys('1', 'space')
        assert s.line_with('✗ a goal is already running on /fibonacci — s cancels it')
        await s.keys('s')
        assert s.line_with('RESULT', 'CANCELED', '2.4 s · last feedback')
        assert s.line_with('sequence: [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]')
        assert s.line_with(FIB, '■ goal canceled after 2.4 s')
        assert '◓' not in s.text() and '◐' not in s.text()
        assert s.line_with('▶ Send goal space') and 'a goal is running' not in s.text()
        await s.shot('action-canceled', expect='s canceled it: RESULT has a yellow CANCELED pill, "2.4 s · last '
                     'feedback" and the last sequence; ACTIVITY "■ goal canceled after 2.4 s" in yellow; no spinner '
                     'in the tab or the top bar; "▶ Send goal space" is blue again and Cancel is dim')

        await s.keys('enter', 'c', '6', 'escape', 'space')
        await s.advance(1.8)  # Order 6: five feedbacks, then the result.
        assert s.line_with('RESULT', 'SUCCEEDED', '1.8 s')
        assert s.line_with('sequence: [0, 1, 1, 2, 3, 5, 8]')
        assert s.line_with(FIB, '✓ goal succeeded · 1.8 s')
        await s.shot('action-succeeded', expect='order 6 sent and done: RESULT has a green SUCCEEDED pill, "1.8 s" and '
                     'the result "sequence: [0, 1, 1, 2, 3, 5, 8]"; GOAL shows "[ ] history (2)" in its title; ACTIVITY '
                     '"✓ goal succeeded · 1.8 s" in green')

        s.bridge.failing_actions[FIB] = 'aborted'
        await s.keys('c', '1', '2', 'escape', 'space')
        await s.advance(1.8)
        assert s.line_with('RESULT', 'ABORTED', '1.8 s')
        assert s.line_with(FIB, '✗ goal aborted after 1.8 s')
        await s.shot('action-aborted', expect='the server aborted the goal halfway: RESULT has a red ABORTED pill and '
                     '"1.8 s" with the result it sent, "sequence: [0, 1, 1, 2, 3, 5, 8]"; ACTIVITY "✗ goal aborted '
                     'after 1.8 s" in red')

        del s.bridge.failing_actions[FIB]
        await s.keys('space', 'x')
        await s.advance(0.3)
        assert s.state()['tabs'] == [ROTATE]
        assert s.line_with('ros_tui', '▷ ◓ /fibonacci')
        await s.shot('closed-still-running', expect='/fibonacci closed with its goal running: only the rotate tab is '
                     'left, but the top bar still shows "▷ ◓ /fibonacci" in cyan')
        await s.keys('u')
        assert s.state()['tabs'] == [FIB, ROTATE] and s.state()['active'] == 0
        assert s.line_with('EXECUTING')

        await s.advance(3.6)
        await s.keys('l', 'enter')
        assert s.state()['path'] == ['tabs', FIB, 'result'] and s.line_with('SUCCEEDED', '3.6 s')
        assert s.line_with('▍sequence: [0, 1, 1, 2, 3, 5, 8, 13, 21, 34,') and s.line_with('▍  55, 89, 144]')
        await s.shot('action-wrapped', expect='u reopened /fibonacci and its order-12 goal succeeded; inside RESULT (blue '
                     'border) the long sequence wraps onto a second, indented line ("55, 89, 144]"), and the current-row '
                     'band covers both lines')
