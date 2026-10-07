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

"""The action entry (ros_tui/ui/entries/action.py), without textual.

The nav model runs over the live demo world (FakeBridge.demo(), plus /turtle1/rotate_absolute from
rotate_demo() for a second action). Time only moves in `advance`, which ticks the model every 0.1 s
as the app does; /fibonacci sends a feedback every 0.3 s (order N: N-1 of them), then its result.
Expectations follow the design's actions branches of send(), secondary() and renderEntry.
"""

import pytest
from harness.fake_bridge import ROTATE_ACTION, FakeBridge, rotate_demo
from ros_tui.ros.events import ActionEvent, ActionEventKind
from ros_tui.ui.entries import entry_router
from ros_tui.ui.entries.action import CANCELED, EXECUTING, FAILED, REJECTED, SENDING, SUCCEEDED, spinner
from ros_tui.ui.fields import flat_text
from ros_tui.ui.nav import AREA, NavState, Running, Tab

FIB = Tab('actions', '/fibonacci')
ROTATE = Tab('actions', ROTATE_ACTION.name)
OPEN_FIB = ['/', *'fib', 'enter']
OPEN_ROTATE = ['/', *'rotate', 'enter']


def order(n: int) -> list[str]:
    """Into GOAL, type the order, keep it (the cursor stays inside GOAL)."""
    return ['enter', 'enter', *str(n), 'escape']


def action_nav(*keys, bridge=None):
    bridge = bridge or FakeBridge.demo()
    nav = NavState(entry_router(bridge), clock=bridge.now)
    nav.set_catalog(bridge.latest_graph)
    press(nav, *keys)
    return nav, bridge


def press(nav, *keys):
    for key in keys:
        nav.handle_key(key)


def advance(nav, bridge, seconds):
    """Move the clock in 0.1 s steps, ticking the model after each; how many ticks asked to redraw."""
    redraws = 0
    for _ in range(round(seconds / 0.1)):
        bridge.clock.advance(0.1)
        redraws += nav.tick()
    return redraws


def entry(nav):
    return nav.provider.for_tab(FIB)


def goal(nav, tab=FIB):
    return entry(nav).data(tab).goal


def shown(nav, tab=FIB):
    """What RESULT shows: ('feedback' or 'result', {field: value as shown})."""
    what, rows = entry(nav).result_rows(tab)
    return what, {row.field: flat_text(row) for row in rows}


def activity(nav):
    return [(line.text, line.cls) for line in nav.activity]


def test_open_loads_the_goal():
    nav, _ = action_nav(*OPEN_FIB)
    data = entry(nav).data(FIB)
    assert [(row.field, row.text) for row in data.editor.rows()] == [('order', '0')]
    assert data.goal is None and shown(nav) == ('', {})
    assert [area.title for area in nav.areas()] == ['GOAL', 'RESULT']


def test_space_sends_the_goal_and_feedback_streams_in():
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space')
    assert [(name, sent.order) for name, _, sent in bridge.sent_goals] == [('/fibonacci', 12)]
    assert goal(nav).state == EXECUTING and goal(nav).running
    assert activity(nav)[0] == ('▶ goal sent · order: 12', 'c')
    assert nav.log[0] == ('space', 'sent a goal to /fibonacci')
    assert shown(nav) == ('feedback', {})  # Nothing in yet: "waiting for feedback…".
    advance(nav, bridge, 0.9)
    assert shown(nav) == ('feedback', {'sequence': '[0, 1, 1, 2, 3]'})
    assert goal(nav).feedbacks == 3 and goal(nav).elapsed(bridge.now()) == pytest.approx(0.9)
    advance(nav, bridge, 0.6)
    assert shown(nav) == ('feedback', {'sequence': '[0, 1, 1, 2, 3, 5, 8]'})


def test_a_goal_succeeds_with_its_result():
    nav, bridge = action_nav(*OPEN_FIB, *order(4), 'space')
    advance(nav, bridge, 1.2)  # Three feedbacks, then the result.
    assert goal(nav).state == SUCCEEDED and not goal(nav).running
    assert shown(nav) == ('result', {'sequence': '[0, 1, 1, 2, 3]'})
    assert activity(nav)[0] == ('✓ goal succeeded · 1.2 s', 'g')
    assert goal(nav).elapsed(bridge.now() + 5) == pytest.approx(1.2)  # The time stops at the end.
    assert entry(nav).executing() is None and nav.running('actions', '/fibonacci') == ()


def test_s_cancels_and_keeps_the_last_feedback():
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space')
    advance(nav, bridge, 0.6)
    press(nav, 's')
    assert bridge.cancelled == ['/fibonacci'] and len(bridge.sent_goals) == 1
    assert goal(nav).state == CANCELED
    assert shown(nav) == ('feedback', {'sequence': '[0, 1, 1, 2]'})
    assert activity(nav)[0] == ('■ goal canceled after 0.6 s', 'y')
    assert nav.log[0] == ('s', 'canceling the goal')


def test_s_before_the_goal_is_accepted_cancels_it_once_it_is():
    bridge = FakeBridge()  # Canned: the goal's events come by hand.
    nav, _ = action_nav(*OPEN_FIB, 'space', 's', bridge=bridge)
    assert goal(nav).state == SENDING and bridge.cancelled == []
    assert nav.log[0] == ('s', 'canceling the goal once the server accepts it')
    bridge.on_event(ActionEvent(FIB.name, ActionEventKind.ACCEPTED))
    assert goal(nav).state == EXECUTING and bridge.cancelled == [FIB.name]


def test_s_with_nothing_running_sends_nothing():
    nav, bridge = action_nav(*OPEN_FIB, 's')
    assert nav.log[0] == ('s', 'nothing running here') and bridge.cancelled == []


def test_one_goal_at_a_time_on_the_same_action():
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space', 'space')
    assert len(bridge.sent_goals) == 1
    assert nav.errline(FIB) == 'a goal is already running on /fibonacci — s cancels it'
    assert activity(nav)[0] == ('✗ a goal is already running on /fibonacci — s cancels it', 'r')
    assert nav.log[0] == ('space', 'a goal is already running')
    advance(nav, bridge, 3.6)  # It ends; now space sends again.
    press(nav, 'space')
    assert len(bridge.sent_goals) == 2 and nav.errline(FIB) == ''


def test_one_goal_at_a_time_across_actions():
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space', *OPEN_ROTATE, 'space', bridge=rotate_demo())
    assert nav.tab == ROTATE and len(bridge.sent_goals) == 1
    assert nav.errline(ROTATE) == 'a goal is already running on /fibonacci'
    press(nav, 's')  # s only cancels the goal of its own tab.
    assert nav.log[0] == ('s', 'nothing running here — the goal runs on /fibonacci') and bridge.cancelled == []
    press(nav, '1', 's', '2', 'space')
    assert [name for name, _, _ in bridge.sent_goals] == ['/fibonacci', ROTATE_ACTION.name]


def test_feedback_floats_show_readable():
    nav, bridge = action_nav(*OPEN_ROTATE, 'enter', 'enter', *'1.5707963', 'escape', 'space', bridge=rotate_demo())
    advance(nav, bridge, 0.3)
    assert shown(nav, ROTATE) == ('feedback', {'remaining': '1.25664'})
    assert goal(nav, ROTATE).feedback['remaining'] == pytest.approx(1.2566370964050293)  # Kept exact.


@pytest.mark.parametrize('failure, state, line', [
    ('aborted', 'ABORTED', '✗ goal aborted after 1.8 s'),
    ('rejected', REJECTED, '✗ goal rejected by the server'),
    ('action server /fibonacci not available', FAILED, '✗ goal failed: action server /fibonacci not available'),
])
def test_a_goal_that_fails_says_so(failure, state, line):
    bridge = FakeBridge.demo()
    bridge.failing_actions['/fibonacci'] = failure
    nav, _ = action_nav(*OPEN_FIB, *order(12), 'space', bridge=bridge)
    advance(nav, bridge, 1.8)
    assert goal(nav).state == state and not goal(nav).running
    assert activity(nav)[0] == (line, 'r')
    assert entry(nav).executing() is None  # A new goal can go out.


def test_the_spinner_turns_four_times_a_second():
    assert [spinner(t) for t in (0.0, 0.25, 0.5, 0.75, 1.0)] == ['◐', '◓', '◑', '◒', '◐']
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space')
    assert nav.running('actions', '/fibonacci') == (Running('◐', 'running', 'live'),)
    advance(nav, bridge, 0.3)
    assert nav.running_all() == [(FIB, Running('◓', 'running', 'live'))]


def test_the_tick_redraws_only_for_what_shows():
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space')
    assert advance(nav, bridge, 1.0) == 10  # Its own tab shows the time, to a tenth of a second.
    press(nav, '0')
    advance(nav, bridge, 0.7)  # Past the highlight of the fresh "goal sent" activity line.
    assert advance(nav, bridge, 1.0) == 4  # Elsewhere only the spinner in the top bar turns.


def test_a_goal_keeps_running_when_its_tab_closes():
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space', 'x')
    assert nav.tabs == [] and goal(nav).running
    assert nav.log[0] == ('x', 'closed /fibonacci — u reopens it')  # Not canceled: that would be a send.
    assert nav.running('actions', '/fibonacci')
    advance(nav, bridge, 3.6)
    assert goal(nav).state == SUCCEEDED and activity(nav)[0][0] == '✓ goal succeeded · 3.6 s'


def test_history_and_undo_stay_in_the_entry():
    nav, bridge = action_nav(*OPEN_FIB, *order(12), 'space')
    advance(nav, bridge, 3.6)
    assert nav.layer == AREA
    press(nav, 'c', '5', 'escape', 'u')
    assert entry(nav).data(FIB).editor.to_plain() == {'order': 12}
    press(nav, 'u')  # The first edit, before the send.
    assert entry(nav).data(FIB).editor.to_plain() == {'order': 0}
    press(nav, 'u')
    assert nav.log[0] == ('u', 'nothing to undo here') and nav.toast.text == 'nothing to undo here'
    press(nav, '[')  # The send is in the history.
    assert entry(nav).data(FIB).editor.to_plain() == {'order': 12}
