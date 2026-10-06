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

"""The topic entry (ros_tui/ui/entries/topic.py), without textual.

The nav model runs over the live demo world (FakeBridge.demo()). Time only moves in `advance`,
which ticks the model every 0.1 s as the app does, so echoes drain at known moments. Expectations
follow the design's topics branches of primary(), secondary(), repeat(), editRate() and renderEntry.
"""

import pytest
from harness.fake_bridge import FakeBridge
from ros_tui.ros.message_yaml import message_structure
from ros_tui.ui.entries import entry_router
from ros_tui.ui.entries.topic import ECHOING, parse_rate
from ros_tui.ui.fields import flat_rows, flat_text, readable
from ros_tui.ui.nav import AREA, EDIT, IN, NavState, Running, Tab

CHATTER = Tab('topics', '/chatter')
INBOX = Tab('topics', '/inbox')
OPEN_CHATTER = ['/', *'chat', 'enter']
OPEN_INBOX = ['/', *'inbox', 'enter']
TYPE_HELLO = ['enter', 'enter', *'hello', 'enter']  # Into MESSAGE, edit data, keep it.


def topic_nav(*keys, bridge=None):
    bridge = bridge or FakeBridge.demo()
    nav = NavState(entry_router(bridge), clock=bridge.now)
    nav.set_catalog(bridge.latest_graph, {name: 1 for name in bridge.feeds})
    press(nav, *keys)
    return nav, bridge


def press(nav, *keys):
    for key in keys:
        nav.handle_key(key)


def advance(nav, bridge, seconds):
    for _ in range(round(seconds / 0.1)):
        bridge.clock.advance(0.1)
        nav.tick()


def entry(nav):
    return nav.provider.for_tab(CHATTER)


def data(nav, tab=CHATTER):
    return entry(nav).data(tab)


def shown(nav, tab=CHATTER):
    return {row.field: None if row.value is None else flat_text(row) for row in entry(nav).echo_rows(nav, tab)}


def activity(nav):
    return [line.text for line in nav.activity]


# ---------- opening ----------

def test_a_published_topic_opens_in_echo_and_an_unpublished_one_in_publish():
    nav, bridge = topic_nav(*OPEN_CHATTER)
    assert nav.entry_mode() == 'echo' and [area.id for area in nav.areas()] == ['out']
    assert data(nav).counts == (1, 0) and bridge.topic_counts_requests == ['/chatter']
    assert shown(nav) == {'data': None} and nav.row_count() == 1
    press(nav, *OPEN_INBOX)
    assert nav.entry_mode() == 'publish' and [area.id for area in nav.areas()] == ['msg']
    assert data(nav, INBOX).counts == (0, 1)


def test_reopening_asks_for_the_counts_again_and_keeps_the_mode():
    nav, bridge = topic_nav(*OPEN_CHATTER, 'e', '0', *OPEN_CHATTER)
    assert nav.entry_mode() == 'publish' and bridge.topic_counts_requests == ['/chatter', '/chatter']


# ---------- echo ----------

def test_space_starts_the_echo_and_the_tick_shows_the_newest_message():
    nav, bridge = topic_nav(*OPEN_CHATTER, 'space')
    assert '/chatter' in bridge.subscriptions and activity(nav) == ['◉ echo started']
    assert nav.running('topics', '/chatter') == (ECHOING,) and nav.running_all() == [(CHATTER, ECHOING)]
    advance(nav, bridge, 3.0)
    assert shown(nav) == {'data': "'chatter 3'"}
    echo = data(nav).echo
    assert (echo.received, echo.dropped, echo.hz) == (3, 0, pytest.approx(1.0))


def test_space_again_stops_it():
    nav, bridge = topic_nav(*OPEN_CHATTER, 'space')
    advance(nav, bridge, 1.0)
    press(nav, 'space')
    assert bridge.subscriptions == {} and data(nav).echo is None
    assert activity(nav)[0] == '■ echo stopped' and nav.running_all() == []
    assert shown(nav) == {'data': None}


def test_the_echo_keeps_running_in_other_tabs():
    nav, bridge = topic_nav(*OPEN_CHATTER, 'space', '0')
    advance(nav, bridge, 2.0)
    assert nav.tab is None and nav.running('topics', '/chatter') == (ECHOING,)
    press(nav, '1')
    assert shown(nav) == {'data': "'chatter 2'"}


def test_going_inside_freezes_the_values_and_counts_what_arrives():
    nav, bridge = topic_nav(*OPEN_CHATTER, 'space')
    advance(nav, bridge, 2.0)
    press(nav, 'enter')
    assert nav.layer == AREA and entry(nav).frozen(nav, CHATTER)
    assert nav.footer().esc == 'go live' and nav.footer().enter == 'show / hide field'
    advance(nav, bridge, 3.0)
    assert shown(nav) == {'data': "'chatter 2'"} and data(nav).new_since == 3
    press(nav, 'escape')
    assert nav.layer == IN and not entry(nav).frozen(nav, CHATTER)
    assert nav.log[0] == ('esc', 'out of the latest message: values are live again')
    assert shown(nav) == {'data': "'chatter 5'"}
    advance(nav, bridge, 0.1)
    assert data(nav).new_since == 0


def test_leaving_by_another_way_goes_live_too():
    """Frozen is where the cursor is, not a flag: switching tabs or modes can't leave it stuck."""
    nav, bridge = topic_nav(*OPEN_CHATTER, 'space', 'enter')
    advance(nav, bridge, 2.0)
    press(nav, '0')
    advance(nav, bridge, 1.0)
    press(nav, '1')
    assert shown(nav) == {'data': "'chatter 3'"} and data(nav).new_since == 0


def test_inside_without_an_echo_is_not_frozen():
    nav, _ = topic_nav(*OPEN_CHATTER, 'enter')
    assert nav.layer == AREA and not entry(nav).frozen(nav, CHATTER)
    assert nav.footer().esc == 'back out'


def test_enter_on_a_field_hides_and_shows_it():
    nav, _ = topic_nav(*OPEN_CHATTER, 'enter', 'enter')
    assert data(nav).hidden == {'data'} and nav.log[0] == ('enter', 'hid data') and nav.layer == AREA
    press(nav, 'enter')
    assert data(nav).hidden == set() and nav.log[0] == ('enter', 'showing data')


def test_nobody_publishing_shows_no_values():
    nav, bridge = topic_nav(*OPEN_INBOX, 'e', 'space')
    advance(nav, bridge, 1.0)
    assert entry(nav).publishers(nav, INBOX) == 0 and shown(nav, INBOX) == {'data': None}


def test_s_in_echo_only_explains():
    nav, bridge = topic_nav(*OPEN_CHATTER, 'space', 's')
    assert nav.log[0] == ('s', 'space stops the echo; going into the latest message freezes it')
    assert data(nav).echo is not None


def test_the_echo_drain_keeps_only_the_newest_message():
    nav, bridge = topic_nav('/', *'counter', 'enter', 'space')
    advance(nav, bridge, 1.0)
    counter = Tab('topics', '/counter')
    echo = data(nav, counter).echo
    assert echo.received == 50 and echo.hz == pytest.approx(50.0) and shown(nav, counter) == {'data': '50'}


def test_flat_rows_open_nested_messages_down_to_compact_ones():
    fields = message_structure('msg', 'geometry_msgs/msg/PoseWithCovarianceStamped')
    rows = flat_rows(fields, None)
    assert [row.field for row in rows] == ['header', 'pose.pose.position', 'pose.pose.orientation', 'pose.covariance']
    assert all(row.value is None for row in rows)
    rows = flat_rows(fields, {'header': {'stamp': {'sec': 1, 'nanosec': 0}, 'frame_id': 'map'},
                              'pose': {'pose': {'position': {'x': 1.0, 'y': 0.0, 'z': 0.0},
                                                'orientation': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0}},
                                       'covariance': [0.0, 0.5]}})
    assert [flat_text(row) for row in rows] == [
        '{stamp: {sec: 1, nanosec: 0}, frame_id: map}', '{x: 1.0, y: 0.0, z: 0.0}',
        '{x: 0.0, y: 0.0, z: 0.0, w: 1.0}', '[0.0, 0.5]']


@pytest.mark.parametrize('value, shown', [
    (1.0806046117362795, 1.0806), (0.479425538604203, 0.479426), (1e-7, 1e-7), (1.23456789e-5, 1.23457e-5),
    (1728036001.5, 1728036002.0), (0.0, 0.0), (float('inf'), float('inf')), (3, 3), (True, True), ('1.23456789', '1.23456789'),
])
def test_readable_cuts_floats_for_display_only(value, shown):
    assert readable(value) == shown and readable({'a': [value]}) == {'a': [shown]}


def test_the_echo_shows_readable_floats_and_keeps_them_all():
    fields = message_structure('msg', 'geometry_msgs/msg/Point')
    row = flat_rows(fields, {'x': 1.0806046117362795, 'y': 0.1, 'z': 0.0})[0]
    assert flat_text(row) == '1.0806' and row.value == 1.0806046117362795


def test_the_tick_redraws_only_when_the_active_tab_shows_something_new():
    nav, bridge = topic_nav(*OPEN_CHATTER)
    advance(nav, bridge, 0.1)
    assert not nav.tick()  # Nothing runs: an idle app never redraws.
    press(nav, 'space')
    bridge.clock.advance(1.0)
    assert nav.tick() and not nav.tick()  # A message arrived; then nothing new.
    press(nav, '0')
    bridge.clock.advance(1.0)
    assert not nav.tick()  # The echo runs on, but nothing on the ☰ list changes.
    press(nav, '1')
    assert shown(nav) == {'data': "'chatter 2'"}


# ---------- publish ----------

def test_space_publishes_the_message_once():
    nav, bridge = topic_nav(*OPEN_INBOX, *TYPE_HELLO, 'space')
    assert [(name, message.data) for name, _, message in bridge.published] == [('/inbox', 'hello')]
    assert activity(nav) == ['✓ published · data: hello'] and data(nav, INBOX).history == [{'data': 'hello'}]


def test_ctrl_s_in_insert_keeps_the_value_and_publishes():
    nav, bridge = topic_nav(*OPEN_INBOX, 'enter', 'enter', *'hi', 'ctrl+s')
    assert nav.layer == AREA and [message.data for _, _, message in bridge.published] == ['hi']


def test_r_repeats_at_the_rate_until_s_stops_it():
    nav, bridge = topic_nav(*OPEN_INBOX, *TYPE_HELLO, 'r')
    assert bridge.periodic_started == [('/inbox', 10.0)] and activity(nav)[0] == '↻ repeating at 10 Hz'
    assert nav.running('topics', '/inbox') == (Running('↻', '10 Hz', 'ok'),)
    advance(nav, bridge, 1.0)
    assert data(nav, INBOX).repeat.sent(nav.clock()) == 10 == bridge.periodic_sent['/inbox']
    press(nav, 'r')
    assert bridge.periodic_started == [('/inbox', 10.0)] and nav.toast.text == 'already repeating at 10 Hz — s stops it'
    press(nav, 's')
    assert bridge.periodic_stopped == ['/inbox'] and data(nav, INBOX).repeat is None
    assert activity(nav)[0] == '■ repeat stopped after 10 sent' and nav.running_all() == []
    press(nav, 's')
    assert nav.log[0] == ('s', 'nothing running here')


def test_r_in_echo_sends_nothing():
    nav, bridge = topic_nav(*OPEN_CHATTER, 'r')
    assert bridge.periodic_started == [] and nav.entry_mode() == 'echo'
    assert nav.log[0] == ('r', 'r repeats a publish — e switches to Publish')


def test_a_repeat_loops_back_into_an_echo_on_the_same_topic():
    nav, bridge = topic_nav(*OPEN_INBOX, *TYPE_HELLO, 'r', 'e', 'space')
    advance(nav, bridge, 1.0)
    assert shown(nav, INBOX) == {'data': "'hello'"} and data(nav, INBOX).echo.received == 10
    assert nav.running('topics', '/inbox') == (ECHOING, Running('↻', '10 Hz', 'ok'))


# ---------- the rate ----------

@pytest.mark.parametrize('text, rate', [('5', 5.0), (' 0.1 ', 0.1), ('100', 100.0), ('2.5', 2.5)])
def test_parse_rate(text, rate):
    assert parse_rate(text) == rate


@pytest.mark.parametrize('text', ['0', '0.05', '500', 'x', '', 'nan', 'inf', '-1'])
def test_parse_rate_rejects(text):
    with pytest.raises(ValueError) as error:
        parse_rate(text)
    assert str(error.value) == f'rate must be 0.1–100 Hz, got "{text.strip()}"'


def test_the_rate_is_the_default_until_the_echo_measures_the_publisher():
    nav, bridge = topic_nav(*OPEN_CHATTER)
    assert (entry(nav).rate(CHATTER), entry(nav).rate_note(CHATTER)) == (10.0, 'default')
    press(nav, 'space')
    advance(nav, bridge, 3.0)
    press(nav, 'space', 'e')
    assert (entry(nav).rate(CHATTER), entry(nav).rate_note(CHATTER)) == (1.0, 'matches the publisher')
    assert nav.label_vars()['rate'] == '1'


def test_R_types_a_new_rate():
    nav, _ = topic_nav(*OPEN_INBOX, 'R')
    editing = nav.editing
    assert nav.layer == EDIT and (editing.area, editing.value, editing.fresh) == ('rate', '10', True)
    assert nav.path() == ('tabs', '/inbox', 'repeat rate', 'editing')
    press(nav, '5', 'enter')
    assert nav.layer == IN and entry(nav).rate(INBOX) == 5.0 and entry(nav).rate_note(INBOX) == 'your rate'
    assert nav.log[0] == ('enter', 'repeat rate 5 Hz (u undoes)')
    press(nav, 'u')
    assert entry(nav).rate(INBOX) == 10.0 and nav.log[0] == ('u', 'repeat rate on /inbox back to 10 Hz')


def test_R_from_echo_switches_to_publish():
    nav, _ = topic_nav(*OPEN_CHATTER, 'R')
    assert nav.entry_mode() == 'publish' and nav.layer == EDIT and nav.editing.back == IN


def test_a_bad_rate_stays_in_insert_and_esc_drops_it():
    nav, _ = topic_nav(*OPEN_INBOX, 'R', *'500', 'enter')
    assert nav.layer == EDIT and nav.errline(INBOX) == 'rate must be 0.1–100 Hz, got "500"'
    press(nav, 'escape')
    assert nav.layer == IN and entry(nav).rate(INBOX) == 10.0
    assert nav.toast.text == 'rate must be 0.1–100 Hz, got "500" — kept the old value'


def test_a_new_rate_restarts_a_running_repeat():
    nav, bridge = topic_nav(*OPEN_INBOX, 'r')
    advance(nav, bridge, 1.0)
    press(nav, 'R', '5', 'enter')
    assert bridge.periodic_started == [('/inbox', 10.0), ('/inbox', 5.0)]
    assert activity(nav)[0] == '↻ rate now 5 Hz'
    assert nav.log[0] == ('enter', 'repeat rate 5 Hz (applied to the running repeat) (u undoes)')
    advance(nav, bridge, 1.0)
    assert data(nav, INBOX).repeat.sent(nav.clock()) == 15
    press(nav, 'u')
    assert bridge.periodic_started[-1] == ('/inbox', 10.0) and activity(nav)[0] == '↻ rate now 10 Hz'


def test_the_rate_command():
    nav, _ = topic_nav(*OPEN_INBOX, ':', *'rate 2', 'enter')
    assert entry(nav).rate(INBOX) == 2.0 and nav.toast.text == 'repeat rate 2 Hz'
    assert nav.log[0] == (':rate', 'repeat rate on /inbox is 2 Hz (u undoes)')
    press(nav, ':', *'rate x', 'enter')
    assert entry(nav).rate(INBOX) == 2.0 and nav.errline(INBOX) == 'rate must be 0.1–100 Hz, got "x"'
    press(nav, 'u')
    assert entry(nav).rate(INBOX) == 10.0


def test_the_rate_command_outside_a_topic():
    nav, _ = topic_nav('/', *'add', 'enter', ':', *'rate 2', 'enter')
    assert nav.toast.text == ':rate works in a topic tab'


# ---------- switching ----------

def test_e_switches_mode_and_keeps_the_message():
    nav, _ = topic_nav(*OPEN_INBOX, 'enter', 'enter', *'he', 'escape', 'e')  # In insert, e types.
    assert nav.entry_mode() == 'echo' and nav.layer == IN and nav.log[0] == ('e', 'now in echo')
    assert data(nav, INBOX).editor.to_plain() == {'data': 'he'}
    press(nav, ':', *'pub', 'enter')
    assert nav.entry_mode() == 'publish'
