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

"""Step 9: the design's "Try this" steps 1–9, end to end, as one scenario over the live demo world.

Each `Step` in STEPS is part of one try-step: its keys (`Wait(s)` lets s seconds pass), the footer
state it ends in (mode, breadcrumb, active tab, and the toast if it matters),
a check of what else the screen shows, and one shot whose `expect` quotes the try-step.

Adapted to the decisions taken: no `.` (step 5 steps through the history with [ ] instead), the
action is /fibonacci (nav2's navigate_to_pose isn't installed), and /goal_pose's orientation is
j j j away (pose starts unfolded). Design references: register-copied, paste-mismatch,
activity-strip, log-view-times (docs/design/reference_shots.json).
"""

from typing import Callable, NamedTuple

import pytest
from harness.screens import ui_session
from ros_tui.ui.next_app import NextApp

pytestmark = [pytest.mark.ui, pytest.mark.shots]

YAW_90 = '{x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}'


def lines(s) -> list[str]:
    return s.text().splitlines()


def line_with(s, *parts) -> str:
    """The first screen line holding all of `parts` ('' if none)."""
    return next((line for line in lines(s) if all(part in line for part in parts)), '')


def strip(s) -> list[str]:
    """The activity strip's lines: its header and the (up to) three newest lines above the footer."""
    screen = lines(s)
    head = next(i for i, line in enumerate(screen) if 'ACTIVITY · ALL TABS' in line)
    return screen[head:-1]


class Wait(NamedTuple):
    """In a step's keys: let this many seconds of (simulated) time pass."""
    seconds: float


class Step(NamedTuple):
    id: str  # The shot's name.
    try_step: int  # The design's try-step (1–9) it is part of.
    title: str  # What the try-step says to do, as the shot's expect quotes it.
    keys: list  # Textual key names, and Wait(seconds).
    footer: tuple  # (mode, breadcrumb, active tab) it ends in.
    toast: str | None  # The toast it ends with, when that matters.
    check: Callable  # What else the screen must show.
    detail: str  # What the shot shows, for the verifier.


async def play(s, keys: list) -> None:
    for key in keys:
        if isinstance(key, Wait):
            await s.advance(key.seconds)
        else:
            await s.keys(key)


def check_footer(s, step: Step) -> None:
    state = s.state()
    assert (state['mode'], state['path'], state['active']) == step.footer, step.id
    if step.toast:
        assert state['toast'] and state['toast'][0] == step.toast, step.id


# Per step: what else the screen must show.
def _open_chatter(s):
    assert line_with(s, '/chatter', 'std_msgs/msg/String') and line_with(s, '▶ Start echo space')


def _echo_live(s):
    assert line_with(s, '[x] data', "'chatter 3'") and line_with(s, '● live')
    assert line_with(s, '09:41:00', '/chatter', '◉ echo started')


def _echo_frozen(s):
    assert line_with(s, '❄ FROZEN', '+2 new since') and line_with(s, '[x] data', "'chatter 3'")


def _copied(s):
    assert line_with(s, 'ros_tui', 'copied: String from /chatter · p pastes')
    assert s.app.nav.register.values == {'data': 'chatter 3'}  # The frozen one, not the newest (chatter 5).


def _live_again(s):
    assert line_with(s, '● live') and line_with(s, 'copied: String from /chatter')


def _open_inbox(s):
    assert line_with(s, ' Publish ') and line_with(s, '▶ Publish once space')


def _pasted(s):
    assert line_with(s, "data: 'chatter 3'") or line_with(s, 'data: chatter 3')


def _paste_undone(s):
    assert not line_with(s, 'data: chatter 3') and not line_with(s, "data: 'chatter 3'")
    assert s.app.nav.log[0] == ('u', 'undid the paste from /chatter on /inbox')


def _published(s):
    assert s.bridge.published[-1][0] == '/inbox' and s.bridge.published[-1][2].data == 'chatter 3'
    assert line_with(s, '/inbox', '✓ published · data: chatter 3')
    assert s.app.nav.flashing(s.app.nav.tab)  # The Publish button flashes white for 0.5 s.


def _insert(s):
    assert line_with(s, 'INSERT') and line_with(s, 'chatter 3 from tui')


def _kept(s):
    assert line_with(s, 'data: chatter 3 from tui') or line_with(s, "data: 'chatter 3 from tui'")


def _rate(s):
    assert line_with(s, '↻ Repeat at', 'type a rate · enter keeps · 0.1–100 Hz')


def _repeating(s):
    assert line_with(s, '■ Stop repeating at 5 Hz s') and line_with(s, '5 sent')
    assert line_with(s, '/inbox', '↻ repeating at 5 Hz')


def _called(s):
    assert line_with(s, '✓ OK', '50.0 ms') and line_with(s, 'sum: 0')
    assert line_with(s, '/add_two_ints', '✓ response · sum: 0 (50.0 ms)')


def _called_again(s):
    assert line_with(s, 'sum: 19') and line_with(s, '/add_two_ints', '✓ response · sum: 19 (50.0 ms)')
    assert s.app.nav.is_fresh(s.app.nav.activity[0])  # Fresh: highlighted green.


def _history_older(s):
    assert line_with(s, 'history #2/2') and line_with(s, 'a: 0')


def _history_newer(s):
    assert line_with(s, 'a: 19') and line_with(s, 'history #1/2')


def _activity(s):
    rows = strip(s)
    assert 'ACTIVITY · ALL TABS · other tabs dimmed' in rows[0] and ':log for everything' in rows[0]
    assert len(rows) == 4 and all('/add_two_ints' in row for row in rows[1:])
    assert not any(s.app.nav.is_fresh(line) for line in s.app.nav.activity)  # The highlight faded.


def _log(s):
    assert line_with(s, 'All activity', 'entries, newest first · j k move · enter goes there · esc closes')
    assert line_with(s, '▍09:41:00', '/chatter', '◉ echo started')  # G: the oldest line, picked.
    assert line_with(s, '09:41:05', '/inbox', '✓ published · data: chatter 3')


def _log_jump(s):
    assert s.app.nav.logv is None


def _goal_pose(s):
    assert line_with(s, 'header: auto', '[f Header]')


def _quat_helper(s):
    assert line_with(s, '= ' + YAW_90)


def _quat_applied(s):
    assert line_with(s, 'orientation: ' + YAW_90)


def _diag_publish(s):
    assert line_with(s, ' Publish ') and line_with(s, 'level')


def _enum_helper(s):
    assert line_with(s, '0 OK') and line_with(s, '3 STALE')


def _enum_picked(s):
    assert line_with(s, 'level: 1 WARN')


def _enum_typed(s):
    assert line_with(s, 'level: 2 ERROR')


def _goal_sent(s):
    assert line_with(s, 'EXECUTING') and line_with(s, '/fibonacci', '▶ goal sent · order: 12')


def _goal_canceled(s):
    assert line_with(s, 'CANCELED') and line_with(s, '/fibonacci', '■ goal canceled after')


def _tab_jumps(s):
    assert line_with(s, '/add_two_ints', 'example_interfaces/srv/AddTwoInts')


def _list(s):
    assert line_with(s, '/chatter') and line_with(s, '/inbox')


def _closed(s):
    assert '/add_two_ints' not in s.state()['tabs']


def _reopened(s):
    assert s.state()['tabs'][2] == '/add_two_ints'


def _services(s):
    assert s.state()['chip'] == 1 and line_with(s, '/add_two_ints', 'AddTwoInts')
    assert not line_with(s, 'std_msgs/msg/String')  # No topic rows.


def _keys(s):
    assert s.state()['which_key'] == 'all' and line_with(s, 'copy / paste a message') == ''  # Not on the list.


STEPS = (
    Step('1-open-chatter', 1,
         'j k (or arrows) move in the list and tab filters by kind. On /chatter (the first topic), enter opens it as '
         'tab 1.',
         [*'jk', 'tab', 'enter'],
         ('normal', ['tabs', '/chatter'], 0), None,
         _open_chatter, '/chatter open as tab 1 in Echo, a blue "▶ Start echo space" button'),
    Step('2-echo-live', 2,
         'space starts the echo: the values are live.',
         ['space', Wait(3.0)],
         ('normal', ['tabs', '/chatter'], 0), None,
         _echo_live, 'the echo is live: "[x] data \'chatter 3\'", "● live"; ACTIVITY shows "09:41:00 ≋ /chatter ◉ echo '
                     'started"'),
    Step('2-echo-frozen', 2,
         'enter goes into the latest message and the values freeze; "+N new since" keeps rising.',
         ['enter', Wait(2.0)],
         ('normal', ['tabs', '/chatter', 'latest message'], 0), None,
         _echo_frozen, 'blue border inside LATEST MESSAGE, "❄ FROZEN +2 new since", data still \'chatter 3\''),
    Step('2-copied', 2,
         'y copies what you see.',
         ['y'],
         ('normal', ['tabs', '/chatter', 'latest message'], 0), 'copied the frozen String from /chatter',
         _copied, 'the top bar shows the magenta chip "copied: String from /chatter · p pastes"; a blue toast "copied'
                  ' the frozen String from /chatter" bottom right; the register holds chatter 3, not the newest'),
    Step('2-live-again', 2,
         'esc makes the values live again.',
         ['escape'],
         ('normal', ['tabs', '/chatter'], 0), None,
         _live_again, 'the echo is live again ("● live"); the chip stays in the top bar'),
    Step('3-open-inbox', 3,
         '/ inbox enter opens /inbox in Publish.',
         ['slash', *'inbox', 'enter'],
         ('normal', ['tabs', '/inbox'], 1), None,
         _open_inbox, '/inbox open as tab 2 in Publish, MESSAGE "data: \'\'"'),
    Step('3-pasted', 3,
         'p pastes the copied message: both are Strings.',
         ['p'],
         ('normal', ['tabs', '/inbox'], 1), 'pasted from /chatter · u undoes',
         _pasted, 'MESSAGE reads "data: chatter 3"; toast "pasted from /chatter · u undoes"'),
    Step('3-paste-undone', 3,
         'u undoes the paste.',
         ['u'],
         ('normal', ['tabs', '/inbox'], 1), None,
         _paste_undone, 'u: MESSAGE is empty again ("data: \'\'")'),
    Step('3-published', 3,
         'p pastes it again and space publishes it.',
         ['p', 'space'],
         ('normal', ['tabs', '/inbox'], 1), None,
         _published, 'pasted again and published: the "▶ Publish once space" button flashes white; ACTIVITY "≋ /inbox'
                     ' ✓ published · data: chatter 3", highlighted green (fresh)'),
    Step('4-insert', 4,
         'enter enter edits the value: you are in INSERT (see the footer). Type.',
         [Wait(2.0), 'enter', 'enter', 'space', *'from', 'space', *'tui'],  # The paste toast has gone.
         ('insert', ['tabs', '/inbox', 'message', 'editing'], 1), None,
         _insert, 'INSERT (green badge), the data row shows the edit box "chatter 3 from tui" with the cursor'),
    Step('4-kept', 4,
         'esc keeps the value.',
         ['escape'],
         ('normal', ['tabs', '/inbox', 'message'], 1), None,
         _kept, 'back to NORMAL inside MESSAGE, data: chatter 3 from tui'),
    Step('4-rate', 4,
         'R changes the repeat rate: type it in place.',
         [*'R5'],
         ('insert', ['tabs', '/inbox', 'repeat rate', 'editing'], 1), None,
         _rate, 'the rate is typed in place in the Repeat button ("5"), "type a rate · enter keeps · 0.1–100 Hz", '
                'INSERT'),
    Step('4-repeating', 4,
         'enter keeps the rate, r repeats the message at it.',
         ['enter', 'r', Wait(1.0)],
         ('normal', ['tabs', '/inbox', 'message'], 1), None,
         _repeating, '"■ Stop repeating at 5 Hz s", "5 sent" in green; ↻ after /inbox in the tab and top bar; '
                     'ACTIVITY "↻ repeating at 5 Hz"'),
    Step('5-called', 5,
         '/ add enter, space calls /add_two_ints.',
         ['slash', *'add', 'enter', 'space', Wait(0.1)],
         ('normal', ['tabs', '/add_two_ints'], 2), None,
         _called, '/add_two_ints open as tab 3: RESPONSE "✓ OK 50.0 ms", sum: 0; ACTIVITY "▶ called" and "✓ response '
                  '· sum: 0 (50.0 ms)"'),
    Step('5-called-again', 5,
         'Edit a value (enter enter, type, esc), then space calls again.',
         ['enter', 'enter', *'19', 'escape', 'space', Wait(0.1)],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _called_again, 'a: 19 kept and called again: sum: 19; the newest ACTIVITY lines are highlighted green '
                        '(a green band with a green bar in the first cell); the Call button flashes white (0.1 s '
                        'after the send)'),
    Step('5-history-older', 5,
         '[ steps back through what you sent.',
         ['left_square_bracket'],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _history_older, '[ shows the first send (a: 0) and REQUEST says "[ ] history #2/2"'),
    Step('5-history-newer', 5,
         '] steps forward again.',
         ['right_square_bracket'],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _history_newer, '] steps to the newest send again: a: 19, "[ ] history #1/2"'),
    Step('6-activity', 6,
         'The ACTIVITY strip shows every send, response and result, labelled with its entry; lines from other tabs '
         'are dimmed.',
         [Wait(2.0)],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _activity, '"ACTIVITY · ALL TABS · other tabs dimmed" … ":log for everything", then three /add_two_ints '
                    'lines with their times, no longer highlighted'),
    Step('6-log', 6,
         ':log shows all activity, with times. j k move, G goes to the oldest.',
         ['colon', *'log', 'enter', 'G'],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _log, 'the :log view over a veil: "All activity N entries, newest first …", every line with its time, glyph '
               'and entry; G picked the oldest, "09:41:00 ≋ /chatter ◉ echo started"'),
    Step('6-log-jump', 6,
         "enter jumps to that line's tab.",
         ['enter'],
         ('normal', ['tabs', '/chatter'], 0), None,
         _log_jump, 'enter jumped to /chatter (tab 1), its echo still live'),
    Step('7-goal-pose', 7,
         '/ goal enter opens /goal_pose; enter goes into the message: fields with a helper show [f Header] / [f '
         'Quaternion].',
         ['slash', *'goal', 'enter', 'enter'],
         ('normal', ['tabs', '/goal_pose', 'message'], 3), None,
         _goal_pose, '/goal_pose open as tab 4, inside MESSAGE: "header: auto [f Header]"'),
    Step('7-quat-helper', 7,
         'j j j to orientation, f, tab tab to "yaw only", type 90.',
         [*'jjjf', 'tab', 'tab', *'90'],
         ('helper', ['tabs', '/goal_pose', 'message'], 3), None,
         _quat_helper, 'the Quaternion helper under orientation, "yaw only (°)" lit, yaw 90, the preview "= {x: 0.0, '
                       'y: 0.0, z: 0.707107, w: 0.707107}", HELPER badge'),
    Step('7-quat-applied', 7,
         'enter applies it: orientation is a 90° yaw.',
         ['enter'],
         ('normal', ['tabs', '/goal_pose', 'message'], 3), None,
         _quat_applied, f'orientation reads "{YAW_90}"'),
    Step('8-diag-publish', 8,
         '/ diag enter, then e for Publish.',
         ['slash', *'diag', 'enter', 'e'],
         ('normal', ['tabs', '/diagnostic_status'], 4), None,
         _diag_publish, '/diagnostic_status open as tab 5, switched to Publish with e'),
    Step('8-enum-helper', 8,
         'enter into the message; f on level picks OK / WARN / ERROR / STALE.',
         ['enter', 'f'],
         ('helper', ['tabs', '/diagnostic_status', 'message'], 4), None,
         _enum_helper, 'the Enum helper on level: ○ 0 OK … ○ 3 STALE, HELPER badge'),
    Step('8-enum-picked', 8,
         'j, enter picks WARN.',
         ['j', 'enter'],
         ('normal', ['tabs', '/diagnostic_status', 'message'], 4), None,
         _enum_picked, 'level: 1 WARN'),
    Step('8-enum-typed', 8,
         'i, type err, esc: ERROR becomes 2.',
         ['i', 'backspace', *'err', 'escape'],
         ('normal', ['tabs', '/diagnostic_status', 'message'], 4), None,
         _enum_typed, '"err" typed into level became level: 2 ERROR'),
    Step('8-goal-sent', 8,
         'An action has the same editor: / fib enter, set order to 12, space sends the goal.',
         ['slash', *'fib', 'enter', 'enter', 'enter', *'12', 'escape', 'space', Wait(1.0)],
         ('normal', ['tabs', '/fibonacci', 'goal'], 5), None,
         _goal_sent, '/fibonacci open as tab 6: RESULT EXECUTING with live feedback, the spinner in the tab and the '
                     'top bar; ACTIVITY "▶ goal sent · order: …"'),
    Step('8-goal-canceled', 8,
         's cancels it.',
         ['s', Wait(0.5)],
         ('normal', ['tabs', '/fibonacci', 'goal'], 5), None,
         _goal_canceled, 'RESULT CANCELED · last feedback; ACTIVITY "■ goal canceled after …" in yellow'),
    Step('9-tab-jumps', 9,
         '1 2 3 jump between tabs.',
         [*'123'],
         ('normal', ['tabs', '/add_two_ints'], 2), None,
         _tab_jumps, '1 2 3 ended on tab 3, /add_two_ints'),
    Step('9-list', 9,
         '0 is the list.',
         ['0'],
         ('normal', ['tabs', '☰ list'], -1), None,
         _list, 'the ☰ list (only topics: the tab chip from step 1), with ◉ / ↻ in the Here column'),
    Step('9-closed', 9,
         'x closes a tab.',
         [*'3x'],
         ('normal', ['tabs', '/goal_pose'], 2), 'closed /add_two_ints · u undoes',
         _closed, 'x closed /add_two_ints: five tabs left, /goal_pose active; toast "closed /add_two_ints · u undoes"'),
    Step('9-reopened', 9,
         'u reopens it.',
         ['u'],
         ('normal', ['tabs', '/add_two_ints'], 2), None,
         _reopened, 'u reopened /add_two_ints as tab 3'),
    Step('9-services', 9,
         ':services enter narrows the list.',
         ['colon', *'services', 'enter'],
         ('normal', ['tabs', '☰ list'], -1), None,
         _services, ':services: the ☰ list shows only services'),
    Step('9-keys', 9,
         '? shows every key.',
         ['question_mark'],
         ('normal', ['tabs', '☰ list'], -1), None,
         _keys, '? shows every key right now, in groups'),
)


def test_the_steps_cover_try_steps_1_to_9():
    assert sorted({step.try_step for step in STEPS}) == list(range(1, 10))
    assert len({step.id for step in STEPS}) == len(STEPS)


async def test_try_steps_1_to_9():
    async with ui_session(app_factory=NextApp) as s:
        for step in STEPS:
            await play(s, step.keys)
            check_footer(s, step)
            step.check(s)
            await s.shot(step.id, expect=f'Try step {step.try_step}: "{step.title}" — {step.detail}')


async def test_paste_mismatch_and_nothing_to_copy():
    async with ui_session(app_factory=NextApp) as s:
        await s.keys('y')
        assert s.state()['toast'] is None and s.app.nav.log[0] == ('y', 'open an entry first')
        await s.keys('enter', 'y')  # /chatter, not echoing.
        assert s.state()['toast'] == ['start the echo first (space)', 'bad']
        await s.keys('space')
        await s.advance(2.0)
        await s.keys('y', 'slash', *'goal', 'enter', 'p')
        assert s.state()['toast'] == ['copied a String, this needs a PoseStamped', 'bad']
        assert line_with(s, 'copied: String from /chatter · p pastes') and line_with(s, 'header: auto')
        await s.shot('paste-mismatch', expect='/goal_pose (Publish) with "copied: String from /chatter · p pastes" in '
                     'the top bar; p was refused: the red toast "copied a String, this needs a PoseStamped"; MESSAGE '
                     'unchanged (header: auto, pose at zero)')
        await s.keys('slash', *'talker', 'enter', 'y')
        assert s.state()['toast'] == ['nothing to copy on a node', 'bad']
        await s.shot('node-nothing-to-copy', expect='/talker (a node): y shows the red toast "nothing to copy on a node"')
