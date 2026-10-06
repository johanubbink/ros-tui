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

"""The harness itself: ``ui_session`` drives the app over the live ``FakeBridge.demo()``.

Keys and clock advances are recorded in order, a shot carries them with the nav model's state, and
the fake world only moves when the clock does. Run with ``ROS_TUI_SHOTS=1``
(scripts/agent_check.sh does) to get the PNG/SVG/TXT/JSON shots.
"""

import pytest
from harness.fake_bridge import SERVICE_DELAY_S, ManualClock
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]


async def test_echo_chatter():
    async with ui_session() as s:
        await s.shot('start', expect='the ☰ list of the demo world, /chatter on the cursor row')

        await s.keys('enter', 'space')
        assert s.bridge.subscriptions.get('/chatter')
        assert 'chatter 1' not in s.text()  # Nothing happens until the clock moves.
        await s.advance(3.0)
        text = s.text()
        assert "'chatter 3'" in text and 'chatter 4' not in text
        shot = await s.shot('echo-live', expect="/chatter echoing: data 'chatter 3', 3 received · 1.0 Hz")
        assert shot['keys'] == ['enter', 'space', '+3s'] and shot['keys_since_last_shot'] == shot['keys']
        assert shot['state']['path'] == ['tabs', '/chatter'] and shot['state']['tabs'] == ['/chatter']

        await s.keys('space')
        assert not s.bridge.subscriptions.get('/chatter')
        await s.advance(2.0)
        assert 'chatter 4' not in s.text()


async def test_call_add_two_ints():
    async with ui_session() as s:
        await s.keys('slash', *'add', 'enter', 'enter', 'enter', '1', '9', 'tab', '2', '3', 'escape')
        await s.shot('request', expect='/add_two_ints open, REQUEST reads a: 19 and b: 23')

        await s.keys('space')
        _, _, request = s.bridge.service_calls[0]
        assert (request.a, request.b) == (19, 23)
        await s.advance(SERVICE_DELAY_S)
        assert 'sum: 42' in s.text()
        await s.shot('response', expect='RESPONSE ✓ OK in 50.0 ms with sum: 42')


def test_manual_clock_orders_timers():
    clock = ManualClock()
    fired = []
    clock.call_every(0.5, lambda: fired.append(('every', clock.now)))
    timer = clock.call_later(0.75, lambda: fired.append(('later', clock.now)))
    clock.call_later(0.25, timer.cancel)
    clock.advance(1.0)
    assert fired == [('every', 0.5), ('every', 1.0)]
    assert clock.now == 1.0
