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

"""One end-to-end session over the demo world, across every kind of entry.

Each `Step` in STEPS is one stretch of the session: its keys (`Wait(s)` lets s seconds pass), the
footer state it ends in (mode, breadcrumb, active tab, and the toast if it matters), a check of what
else the screen shows, and one shot. It opens and echoes /chatter, copies and pastes into /inbox,
edits and repeats a publish, calls /add_two_ints and steps its history, reads the activity strip and
:log, fills /goal_pose and /diagnostic_status with helpers, sends and cancels a /fibonacci goal, then
jumps, closes and reopens tabs.
"""

from typing import Callable, NamedTuple

import pytest
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]

YAW_90 = '{x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}'


def strip(s) -> list[str]:
    """The activity strip's lines: its header and the (up to) three newest lines above the footer."""
    screen = s.lines()
    head = next(i for i, line in enumerate(screen) if 'ACTIVITY · ALL TABS' in line)
    return screen[head:-1]


class Wait(NamedTuple):
    """In a step's keys: let this many seconds of (simulated) time pass."""
    seconds: float


class Step(NamedTuple):
    id: str  # The shot's name.
    title: str  # What the step does, as the shot's expect quotes it.
    keys: list  # Textual key names, and Wait(seconds).
    footer: tuple  # (mode, breadcrumb, active tab) it ends in.
    toast: str | None  # The toast it ends with, when that matters.
    check: Callable  # What else the screen must show.
    detail: str  # What the shot shows, for the reviewer.


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
    assert s.line_with('/chatter', 'std_msgs/msg/String') and s.line_with('▶ Start echo space')


def _echo_live(s):
    assert s.line_with('[x] data', "'chatter 3'") and s.line_with('● live')
    assert s.line_with('09:41:00', '/chatter', '◉ echo started')


def _echo_frozen(s):
    assert s.line_with('❄ FROZEN', '+2 new since') and s.line_with('[x] data', "'chatter 3'")


def _copied(s):
    assert s.line_with('ros_tui', 'copied: String from /chatter · p pastes')


def _live_again(s):
    assert s.line_with('● live') and s.line_with('copied: String from /chatter')


def _open_inbox(s):
    assert s.line_with(' Publish ') and s.line_with('▶ Publish once space')


def _pasted(s):
    assert s.line_with("data: 'chatter 3'") or s.line_with('data: chatter 3')


def _paste_undone(s):
    assert not s.line_with('data: chatter 3') and not s.line_with("data: 'chatter 3'")


def _published(s):
    assert s.line_with('/inbox', '✓ published · data: chatter 3')


def _insert(s):
    assert s.line_with('INSERT') and s.line_with('chatter 3 from tui')


def _kept(s):
    assert s.line_with('data: chatter 3 from tui') or s.line_with("data: 'chatter 3 from tui'")


def _rate(s):
    assert s.line_with('↻ Repeat at', 'type a rate · enter keeps · 0.1–100 Hz')


def _repeating(s):
    assert s.line_with('■ Stop repeating at 5 Hz s') and s.line_with('5 sent')
    assert s.line_with('/inbox', '↻ repeating at 5 Hz')


def _called(s):
    assert s.line_with('✓ OK', '50.0 ms') and s.line_with('sum: 0')
    assert s.line_with('/add_two_ints', '✓ response · sum: 0 (50.0 ms)')


def _called_again(s):
    assert s.line_with('sum: 19') and s.line_with('/add_two_ints', '✓ response · sum: 19 (50.0 ms)')


def _history_older(s):
    assert s.line_with('history #2/2') and s.line_with('a: 0')


def _history_newer(s):
    assert s.line_with('a: 19') and s.line_with('history #1/2')


def _activity(s):
    rows = strip(s)
    assert 'ACTIVITY · ALL TABS · other tabs dimmed' in rows[0] and ':log for everything' in rows[0]
    assert len(rows) == 4 and all('/add_two_ints' in row for row in rows[1:])


def _log(s):
    assert s.line_with('All activity (', ') ', 'j k move', 'enter goes there')
    assert s.line_with('▍09:41:00', '/chatter', '◉ echo started')  # G: the oldest line, picked.
    assert s.line_with('09:41:05', '/inbox', '✓ published · data: chatter 3')


def _log_jump(s):
    assert s.state()['overlay'] is None


def _goal_pose(s):
    assert s.line_with('header: auto', '[f Header]')


def _quat_helper(s):
    assert s.line_with('= ' + YAW_90)


def _quat_applied(s):
    assert s.line_with('orientation: ' + YAW_90)


def _diag_publish(s):
    assert s.line_with(' Publish ') and s.line_with('level')


def _enum_helper(s):
    assert s.line_with('0 OK') and s.line_with('3 STALE')


def _enum_picked(s):
    assert s.line_with('level: 1 WARN')


def _enum_typed(s):
    assert s.line_with('level: 2 ERROR')


def _goal_sent(s):
    assert s.line_with('EXECUTING') and s.line_with('/fibonacci', '▶ goal sent · order: 12')


def _goal_canceled(s):
    assert s.line_with('CANCELED') and s.line_with('/fibonacci', '■ goal canceled after')


def _tab_jumps(s):
    assert s.line_with('/add_two_ints', 'example_interfaces/srv/AddTwoInts')


def _list(s):
    assert s.line_with('/chatter') and s.line_with('/inbox')


def _closed(s):
    assert '/add_two_ints' not in s.state()['tabs']


def _reopened(s):
    assert s.state()['tabs'][2] == '/add_two_ints'


def _services(s):
    assert s.state()['chip'] == 1 and s.line_with('/add_two_ints', 'AddTwoInts')
    assert not s.line_with('std_msgs/msg/String')  # No topic rows.


def _keys(s):
    assert s.state()['which_key'] == 'all' and s.line_with('copy / paste a message') == ''  # Not on the list.


STEPS = (
    Step('open-chatter',
         'j k (or arrows) move in the list and tab filters by kind. On /chatter (the first topic), enter opens it as '
         'tab 1.',
         [*'jk', 'tab', 'enter'],
         ('normal', ['tabs', '/chatter'], 0), None,
         _open_chatter, '/chatter open as tab 1 in Echo, a blue "▶ Start echo space" button'),
    Step('echo-live',
         'space starts the echo: the values are live.',
         ['space', Wait(3.0)],
         ('normal', ['tabs', '/chatter'], 0), None,
         _echo_live, 'the echo is live: "[x] data \'chatter 3\'", "● live"; ACTIVITY shows "09:41:00 ≋ /chatter ◉ echo '
                     'started"'),
    Step('echo-frozen',
         'enter goes into the latest message and the values freeze; "+N new since" keeps rising.',
         ['enter', Wait(2.0)],
         ('normal', ['tabs', '/chatter', 'latest message'], 0), None,
         _echo_frozen, 'blue border inside LATEST MESSAGE, "❄ FROZEN +2 new since", data still \'chatter 3\''),
    Step('copied',
         'y copies what you see.',
         ['y'],
         ('normal', ['tabs', '/chatter', 'latest message'], 0), 'copied the frozen String from /chatter',
         _copied, 'the top bar shows the magenta chip "copied: String from /chatter · p pastes"; a blue toast "copied'
                  ' the frozen String from /chatter" bottom right; the register holds chatter 3, not the newest'),
    Step('live-again',
         'esc makes the values live again.',
         ['escape'],
         ('normal', ['tabs', '/chatter'], 0), None,
         _live_again, 'the echo is live again ("● live"); the chip stays in the top bar'),
    Step('open-inbox',
         '/ inbox enter opens /inbox in Publish.',
         ['slash', *'inbox', 'enter'],
         ('normal', ['tabs', '/inbox'], 1), None,
         _open_inbox, '/inbox open as tab 2 in Publish, MESSAGE "data: \'\'"'),
    Step('pasted',
         'p pastes the copied message: both are Strings.',
         ['p'],
         ('normal', ['tabs', '/inbox'], 1), 'pasted from /chatter · u undoes',
         _pasted, 'MESSAGE reads "data: chatter 3"; toast "pasted from /chatter · u undoes"'),
    Step('paste-undone',
         'u undoes the paste.',
         ['u'],
         ('normal', ['tabs', '/inbox'], 1), None,
         _paste_undone, 'u: MESSAGE is empty again ("data: \'\'")'),
    Step('published',
         'p pastes it again and space publishes it.',
         ['p', 'space'],
         ('normal', ['tabs', '/inbox'], 1), None,
         _published, 'pasted again and published: the "▶ Publish once space" button flashes white; ACTIVITY "≋ /inbox'
                     ' ✓ published · data: chatter 3", highlighted green (fresh)'),
    Step('insert',
         'enter enter edits the value: you are in INSERT (see the footer). Type.',
         [Wait(2.0), 'enter', 'enter', 'space', *'from', 'space', *'tui'],  # The paste toast has gone.
         ('insert', ['tabs', '/inbox', 'message', 'editing'], 1), None,
         _insert, 'INSERT (green badge), the data row shows the edit box "chatter 3 from tui" with the cursor'),
    Step('kept',
         'esc keeps the value.',
         ['escape'],
         ('normal', ['tabs', '/inbox', 'message'], 1), None,
         _kept, 'back to NORMAL inside MESSAGE, data: chatter 3 from tui'),
    Step('rate',
         'R changes the repeat rate: type it in place.',
         [*'R5'],
         ('insert', ['tabs', '/inbox', 'repeat rate', 'editing'], 1), None,
         _rate, 'the rate is typed in place in the Repeat button ("5"), "type a rate · enter keeps · 0.1–100 Hz", '
                'INSERT'),
    Step('repeating',
         'enter keeps the rate, r repeats the message at it.',
         ['enter', 'r', Wait(1.0)],
         ('normal', ['tabs', '/inbox', 'message'], 1), None,
         _repeating, '"■ Stop repeating at 5 Hz s", "5 sent" in green; ↻ after /inbox in the tab and top bar; '
                     'ACTIVITY "↻ repeating at 5 Hz"'),
    Step('called',
         '/ add enter, space calls /add_two_ints.',
         ['slash', *'add', 'enter', 'space', Wait(0.1)],
         ('normal', ['tabs', '/add_two_ints'], 2), None,
         _called, '/add_two_ints open as tab 3: RESPONSE "✓ OK 50.0 ms", sum: 0; ACTIVITY "▶ called" and "✓ response '
                  '· sum: 0 (50.0 ms)"'),
    Step('called-again',
         'Edit a value (enter enter, type, esc), then space calls again.',
         ['enter', 'enter', *'19', 'escape', 'space', Wait(0.1)],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _called_again, 'a: 19 kept and called again: sum: 19; the newest ACTIVITY lines are highlighted green '
                        '(a green band with a green bar in the first cell); the Call button flashes white (0.1 s '
                        'after the send)'),
    Step('history-older',
         '[ steps back through what you sent.',
         ['left_square_bracket'],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _history_older, '[ shows the first send (a: 0) and REQUEST says "[ ] history #2/2"'),
    Step('history-newer',
         '] steps forward again.',
         ['right_square_bracket'],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _history_newer, '] steps to the newest send again: a: 19, "[ ] history #1/2"'),
    Step('activity',
         'The ACTIVITY strip shows every send, response and result, labelled with its entry; lines from other tabs '
         'are dimmed.',
         [Wait(2.0)],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _activity, '"ACTIVITY · ALL TABS · other tabs dimmed" … ":log for everything", then three /add_two_ints '
                    'lines with their times, not highlighted any more'),
    Step('log',
         ':log shows all activity, with times. j k move, G goes to the oldest.',
         ['colon', *'log', 'enter', 'G'],
         ('normal', ['tabs', '/add_two_ints', 'request'], 2), None,
         _log, 'the :log view over a veil: "All activity (N)  j k move · enter goes there", every line with its time, glyph '
               'and entry; G picked the oldest, "09:41:00 ≋ /chatter ◉ echo started"'),
    Step('log-jump',
         "enter jumps to that line's tab.",
         ['enter'],
         ('normal', ['tabs', '/chatter'], 0), None,
         _log_jump, 'enter jumped to /chatter (tab 1), its echo still live'),
    Step('goal-pose',
         '/ goal enter opens /goal_pose; enter goes into the message: fields with a helper show [f Header] / [f '
         'Quaternion].',
         ['slash', *'goal', 'enter', 'enter'],
         ('normal', ['tabs', '/goal_pose', 'message'], 3), None,
         _goal_pose, '/goal_pose open as tab 4, inside MESSAGE: "header: auto [f Header]"'),
    Step('quat-helper',
         'j j j to orientation, f, tab tab to "yaw only", type 90.',
         [*'jjjf', 'tab', 'tab', *'90'],
         ('helper', ['tabs', '/goal_pose', 'message'], 3), None,
         _quat_helper, 'the Quaternion helper under orientation, "yaw only (°)" lit, yaw 90, the preview "= {x: 0.0, '
                       'y: 0.0, z: 0.707107, w: 0.707107}", HELPER badge'),
    Step('quat-applied',
         'enter applies it: orientation is a 90° yaw.',
         ['enter'],
         ('normal', ['tabs', '/goal_pose', 'message'], 3), None,
         _quat_applied, f'orientation reads "{YAW_90}"'),
    Step('diag-publish',
         '/ diag enter, then e for Publish.',
         ['slash', *'diag', 'enter', 'e'],
         ('normal', ['tabs', '/diagnostic_status'], 4), None,
         _diag_publish, '/diagnostic_status open as tab 5, switched to Publish with e'),
    Step('enum-helper',
         'enter into the message; f on level picks OK / WARN / ERROR / STALE.',
         ['enter', 'f'],
         ('helper', ['tabs', '/diagnostic_status', 'message'], 4), None,
         _enum_helper, 'the Enum helper on level: ○ 0 OK … ○ 3 STALE, HELPER badge'),
    Step('enum-picked',
         'j, enter picks WARN.',
         ['j', 'enter'],
         ('normal', ['tabs', '/diagnostic_status', 'message'], 4), None,
         _enum_picked, 'level: 1 WARN'),
    Step('enum-typed',
         'i, type err, esc: ERROR becomes 2.',
         ['i', 'backspace', *'err', 'escape'],
         ('normal', ['tabs', '/diagnostic_status', 'message'], 4), None,
         _enum_typed, '"err" typed into level became level: 2 ERROR'),
    Step('goal-sent',
         'An action has the same editor: / fib enter, set order to 12, space sends the goal.',
         ['slash', *'fib', 'enter', 'enter', 'enter', *'12', 'escape', 'space', Wait(1.0)],
         ('normal', ['tabs', '/fibonacci', 'goal'], 5), None,
         _goal_sent, '/fibonacci open as tab 6: RESULT EXECUTING with live feedback, the spinner in the tab and the '
                     'top bar; ACTIVITY "▶ goal sent · order: …"'),
    Step('goal-canceled',
         's cancels it.',
         ['s', Wait(0.5)],
         ('normal', ['tabs', '/fibonacci', 'goal'], 5), None,
         _goal_canceled, 'RESULT CANCELED · last feedback; ACTIVITY "■ goal canceled after …" in yellow'),
    Step('tab-jumps',
         '1 2 3 jump between tabs.',
         [*'123'],
         ('normal', ['tabs', '/add_two_ints'], 2), None,
         _tab_jumps, '1 2 3 ended on tab 3, /add_two_ints'),
    Step('list',
         '0 is the list.',
         ['0'],
         ('normal', ['tabs', '☰ list'], -1), None,
         _list, 'the ☰ list (only topics: the tab chip from the first step), with ◉ / ↻ in the Here column'),
    Step('closed',
         'x closes a tab.',
         [*'3x'],
         ('normal', ['tabs', '/goal_pose'], 2), 'closed /add_two_ints · u undoes',
         _closed, 'x closed /add_two_ints: five tabs left, /goal_pose active; toast "closed /add_two_ints · u undoes"'),
    Step('reopened',
         'u reopens it.',
         ['u'],
         ('normal', ['tabs', '/add_two_ints'], 2), None,
         _reopened, 'u reopened /add_two_ints as tab 3'),
    Step('services',
         ':services enter narrows the list.',
         ['colon', *'services', 'enter'],
         ('normal', ['tabs', '☰ list'], -1), None,
         _services, ':services: the ☰ list shows only services'),
    Step('keys',
         '? shows every key.',
         ['question_mark'],
         ('normal', ['tabs', '☰ list'], -1), None,
         _keys, '? shows every key right now, in groups'),
)


async def test_end_to_end_session():
    async with ui_session() as s:
        for step in STEPS:
            await play(s, step.keys)
            check_footer(s, step)
            step.check(s)
            await s.shot(step.id, expect=f'{step.title} — {step.detail}')


async def test_paste_mismatch_and_nothing_to_copy():
    """The refusals' rules are in test_register.py; here what they look like."""
    async with ui_session() as s:
        await s.keys('enter', 'space')
        await s.advance(2.0)
        await s.keys('y', 'slash', *'goal', 'enter', 'p')
        assert s.line_with('copied a String, this needs a PoseStamped')
        assert s.line_with('copied: String from /chatter · p pastes') and s.line_with('header: auto')
        await s.shot('paste-mismatch', expect='/goal_pose (Publish) with "copied: String from /chatter · p pastes" in '
                     'the top bar; p was refused: the red toast "copied a String, this needs a PoseStamped"; MESSAGE '
                     'unchanged (header: auto, pose at zero)')
        await s.keys('slash', *'talker', 'enter', 'y')
        assert s.line_with('nothing to copy on a node')
        await s.shot('node-nothing-to-copy', expect='/talker (a node): y shows the red toast "nothing to copy on a node"')
