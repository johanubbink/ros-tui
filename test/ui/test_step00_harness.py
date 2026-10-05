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

"""Phase 0: the harness itself, on the current (four-tab) UI.

Two scenarios ported from test_ui_pilot.py to ``ui_session`` + the live ``FakeBridge.demo()``:
echo /chatter while the clock runs, and call /add_two_ints with typed values. Run with
``ROS_TUI_SHOTS=1`` (scripts/agent_check.sh does) to get the PNG/SVG/TXT/JSON shots.
"""

import pytest
from harness.fake_bridge import ManualClock
from harness.screens import ui_session
from ros_tui.ui.topic_mode_popup import TopicModePopup
from textual.widgets import OptionList

pytestmark = [pytest.mark.ui, pytest.mark.shots]


async def test_echo_chatter():
    async with ui_session() as s:
        await s.shot('start', expect='Topics tab, list maximized with the six demo topics, filter box focused')

        await s.type_text('chat')
        topics = s.app.query_one('#topics-tab #entity-list', OptionList)
        assert await s.wait_until(lambda: topics.option_count == 1)
        await s.keys('enter')
        assert isinstance(s.app.screen, TopicModePopup)
        await s.shot('mode-popup', expect='popup "Topic: /chatter", std_msgs/msg/String, publishers: 1')

        await s.keys('s', 'ctrl+s')
        assert '/chatter' in s.bridge.subscriptions
        await s.advance(3.0)
        text = s.text()
        assert 'chatter 1' in text and 'chatter 3' in text and 'chatter 4' not in text
        await s.shot('echo-live', expect='subscribe view of /chatter; the echo log shows data: chatter 1, 2 and 3')

        await s.keys('ctrl+s')
        assert '/chatter' not in s.bridge.subscriptions
        await s.advance(2.0)
        assert 'chatter 4' not in s.text()


async def test_call_add_two_ints():
    async with ui_session() as s:
        await s.keys('ctrl+t')
        assert s.state()['active_tab'] == 'services'
        await s.type_text('add')
        services = s.app.query_one('#services-tab #entity-list', OptionList)
        assert await s.wait_until(lambda: services.option_count == 1)
        await s.keys('enter')
        # The cursor lands on the first value; tab jumps to the next one.
        await s.keys('delete', '1', '9', 'tab', 'delete', '2', '3')
        await s.shot('request', expect='Services tab, /add_two_ints selected, editor reads a: 19 and b: 23')

        await s.keys('ctrl+s')
        assert len(s.bridge.service_calls) == 1
        _, _, request = s.bridge.service_calls[0]
        assert (request.a, request.b) == (19, 23)
        await s.advance(0.1)
        assert 'sum: 42' in s.text()
        await s.shot('response', expect='the output log shows "response in … ms" and sum: 42')


def test_manual_clock_orders_timers():
    clock = ManualClock()
    fired = []
    clock.call_every(0.5, lambda: fired.append(('every', clock.now)))
    timer = clock.call_later(0.75, lambda: fired.append(('later', clock.now)))
    clock.call_later(0.25, timer.cancel)
    clock.advance(1.0)
    assert fired == [('every', 0.5), ('every', 1.0)]
    assert clock.now == 1.0
