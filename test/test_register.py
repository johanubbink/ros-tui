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

"""The y / p register (ros_tui/ui/register.py, and y / p in the entries), the activity lines' times
and the send flash, without textual.

The register's type rules are pure. The rest runs the nav model over the live demo world
(FakeBridge.demo()), as test_entries_topic.py does: time only moves in `advance`.
"""

import math

import pytest
from harness.fake_bridge import TopicFeed
from harness.live_world import advance, live_nav, press, toast
from ros_tui.ui.feedback import ActivityLine, clock_text
from ros_tui.ui.nav import NOTHING_TO_UNDO, Tab
from ros_tui.ui.register import Register, type_label
from std_msgs.msg import String

STRING = 'std_msgs/msg/String'
CHATTER = Tab('topics', '/chatter')
INBOX = Tab('topics', '/inbox')
OPEN_CHATTER = ['/', *'chat', 'enter']
OPEN_INBOX = ['/', *'inbox', 'enter']
OPEN_GOAL_POSE = ['/', *'goal', 'enter']
OPEN_ADD = ['/', *'add', 'enter']
OPEN_POSE = ['/', *'locali', 'enter']


def editor(nav, tab):
    return nav.entry(tab).editor


# ---------- the type rules (pure) ----------

def test_a_register_reads_as_its_short_type_and_role():
    assert type_label(STRING, 'message') == 'String'
    assert type_label('example_interfaces/srv/AddTwoInts', 'request') == 'AddTwoInts request'
    assert type_label('example_interfaces/action/Fibonacci', 'goal') == 'Fibonacci goal'
    register = Register.of(STRING, 'message', '/chatter', {'data': 'hi'})
    assert register.chip() == 'copied: String from /chatter · p pastes'


def test_it_pastes_only_into_the_same_type_in_the_same_role():
    register = Register.of(STRING, 'message', '/chatter', {'data': 'hi'})
    assert register.mismatch(STRING, 'message') == ''
    assert register.mismatch('geometry_msgs/msg/PoseStamped', 'message') == \
        'copied a String, this needs a PoseStamped'
    request = Register.of('example_interfaces/srv/AddTwoInts', 'request', '/add_two_ints', {'a': 1, 'b': 2})
    assert request.mismatch('example_interfaces/srv/AddTwoInts', 'request') == ''
    assert request.mismatch('example_interfaces/srv/AddTwoInts', 'goal') == \
        'copied a AddTwoInts request, this needs a AddTwoInts goal'


def test_a_register_keeps_its_own_copy():
    values = {'data': 'hi', 'nested': {'x': 1.0}}
    register = Register.of(STRING, 'message', '/chatter', values)
    values['nested']['x'] = 2.0
    assert register.values == {'data': 'hi', 'nested': {'x': 1.0}}


# ---------- y ----------

def test_y_in_echo_copies_the_latest_message():
    nav, bridge = live_nav(*OPEN_CHATTER, 'space')
    advance(nav, bridge, 2.0)
    press(nav, 'y')
    assert nav.register == Register(STRING, 'message', '/chatter', {'data': 'chatter 2'})
    assert toast(nav) == 'copied the latest String from /chatter' and nav.feedback.toast.kind == 'info'
    assert nav.summary()['register'] == 'String from /chatter'


def test_y_while_frozen_copies_the_frozen_message():
    nav, bridge = live_nav(*OPEN_CHATTER, 'space')
    advance(nav, bridge, 1.0)
    press(nav, 'enter')  # Freeze on chatter 1.
    advance(nav, bridge, 2.0)
    press(nav, 'y')
    assert nav.register.values == {'data': 'chatter 1'}
    assert toast(nav) == 'copied the frozen String from /chatter'


def test_y_copies_the_message_exactly_not_as_it_is_shown():
    nav, bridge = live_nav(*OPEN_POSE, 'space')
    bridge.feeds = {**bridge.feeds, '/chatter': TopicFeed(1.0, lambda index, now: String(data='x' * 300))}
    advance(nav, bridge, 0.5)
    press(nav, 'y')
    position = nav.register.values['pose']['pose']['position']
    assert position['x'] == 2.0 * math.cos(0.5)  # Not the 6 digits LATEST MESSAGE shows.
    press(nav, *OPEN_CHATTER, 'space')
    advance(nav, bridge, 1.0)
    press(nav, 'y')
    assert nav.register.values == {'data': 'x' * 300}  # Not cut at TRUNCATE_STRING_CHARS.


def test_y_in_echo_says_why_there_is_nothing_to_copy():
    nav, bridge = live_nav(*OPEN_CHATTER, 'y')
    assert toast(nav) == 'start the echo first (space)' and nav.register is None
    press(nav, '/', *'inbox', 'enter', 'e', 'space', 'y')  # /inbox in Echo: nobody publishes it.
    assert toast(nav) == 'no messages to copy: nobody publishes /inbox' and nav.register is None


def test_y_in_an_editor_copies_the_editor():
    nav, bridge = live_nav(*OPEN_INBOX, 'enter', 'enter', *'hello', 'enter', 'y')
    assert nav.register == Register(STRING, 'message', '/inbox', {'data': 'hello'}) and toast(nav) == 'copied the message'
    press(nav, *OPEN_ADD, 'y')
    assert nav.register.label == 'AddTwoInts request' and nav.register.values == {'a': 0, 'b': 0}
    assert toast(nav) == 'copied the request'
    press(nav, '/', *'fib', 'enter', 'y')
    assert nav.register.label == 'Fibonacci goal' and toast(nav) == 'copied the goal'


def test_y_on_a_node_copies_nothing():
    nav, bridge = live_nav('/', *'talker', 'enter', 'y')
    assert toast(nav) == 'nothing to copy on a node' and nav.register is None


# ---------- p ----------

def test_p_pastes_the_same_type_as_one_undo_step():
    nav, bridge = live_nav(*OPEN_CHATTER, 'space')
    advance(nav, bridge, 1.0)
    press(nav, 'y', *OPEN_INBOX, 'p')
    assert editor(nav, INBOX).to_plain() == {'data': 'chatter 1'}
    assert toast(nav) == 'pasted from /chatter · u undoes'
    press(nav, 'space')
    assert bridge.published[-1][2].data == 'chatter 1'
    press(nav, 'u')
    assert editor(nav, INBOX).to_plain() == {'data': ''}
    assert nav.feedback.log[0] == ('u', 'undid the paste from /chatter on /inbox')
    press(nav, 'u')
    assert nav.feedback.log[0] == ('u', NOTHING_TO_UNDO)


def test_p_refuses_another_type():
    nav, bridge = live_nav(*OPEN_CHATTER, 'space')
    advance(nav, bridge, 1.0)
    press(nav, 'y', *OPEN_GOAL_POSE)
    before = editor(nav, Tab('topics', '/goal_pose')).to_plain()
    press(nav, 'p')
    assert toast(nav) == 'copied a String, this needs a PoseStamped' and nav.feedback.toast.kind == 'bad'
    assert editor(nav, Tab('topics', '/goal_pose')).to_plain() == before
    press(nav, 'u')
    assert nav.feedback.log[0] == ('u', NOTHING_TO_UNDO)


def test_p_says_what_is_missing():
    nav, bridge = live_nav(*OPEN_INBOX, 'p')
    assert toast(nav) == 'nothing copied yet (y copies)'
    press(nav, 'y', *OPEN_CHATTER, 'p')
    assert toast(nav) == 'switch to Publish (e) to paste'
    press(nav, 'e', 'p')
    assert toast(nav) == 'pasted from /inbox · it was the same already'
    press(nav, '/', *'talker', 'enter', 'p')
    assert toast(nav) == 'nothing to paste into on a node'


# ---------- activity lines and the send flash ----------

def test_activity_lines_carry_the_time_of_day():
    assert clock_text(9 * 3600 + 41 * 60 + 3.7) == '09:41:03'
    assert clock_text(86400 + 5) == '00:00:05'
    nav, bridge = live_nav(*OPEN_ADD)
    advance(nav, bridge, 2.0)
    press(nav, 'space')
    advance(nav, bridge, 0.1)
    assert [(line.time, line.text) for line in nav.feedback.activity] == [
        ('09:41:02', '✓ response · sum: 0 (50.0 ms)'), ('09:41:02', '▶ called · a: 0, b: 0')]
    line = nav.feedback.activity[0]
    assert line == ActivityLine('services', '/add_two_ints', '✓ response · sum: 0 (50.0 ms)', 'g', '09:41:02', line.at)
    assert line.at == pytest.approx(2.05)  # The clock time, for the fresh highlight.


def test_a_new_activity_line_is_fresh_for_a_while():
    nav, bridge = live_nav(*OPEN_ADD, 'space')
    line = nav.feedback.activity[0]
    assert nav.feedback.is_fresh(line) and nav.feedback.fresh_lines() == 1
    advance(nav, bridge, 1.0)
    assert nav.feedback.fresh_lines() == 2  # The response came in at 0.05 s.
    advance(nav, bridge, 0.5)
    bridge.clock.advance(0.12)  # 1.62 s: "called" (at 0.0) has faded, the response (at 0.05) not yet.
    assert nav.tick() and not nav.tick()  # One redraw for the fade, then none.
    assert not nav.feedback.is_fresh(line) and nav.feedback.fresh_lines() == 1
    advance(nav, bridge, 0.1)
    assert nav.feedback.fresh_lines() == 0 and not nav.tick()


def test_a_send_flashes_the_primary_button_for_half_a_second():
    nav, bridge = live_nav(*OPEN_ADD)
    assert not nav.feedback.flashing(nav.tab)
    press(nav, 'space')
    assert nav.feedback.flashing(nav.tab) and not nav.feedback.flashing(INBOX)
    advance(nav, bridge, 0.4)
    assert nav.feedback.flashing(nav.tab)
    bridge.clock.advance(0.1)
    assert nav.tick() and nav.feedback.flash is None


def test_only_a_send_that_goes_out_flashes():
    nav, bridge = live_nav('/', *'talker', 'enter', 'space')  # No changed parameters: nothing goes out.
    assert toast(nav) == 'change a value first (enter edits it)' and nav.feedback.flash is None
    nav, bridge = live_nav(*OPEN_CHATTER, 'space')  # An echo sends nothing to the robot.
    assert nav.feedback.activity[0].text == '◉ echo started' and nav.feedback.flash is None
    nav, bridge = live_nav('/', *'fib', 'enter', 'space')
    advance(nav, bridge, 0.5)
    press(nav, 'space')  # A goal is already running: refused.
    assert nav.feedback.errline(nav.tab).startswith('a goal is already running') and nav.feedback.flash is None
