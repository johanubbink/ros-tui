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

"""
Full-stack smoke: the real app over a real RosBridge and the in-process fixture servers.

The tests drive the app with keys, as a user would, against the fixture servers in
``test/conftest.py`` (which mirror the demo node in ``ros_tui/demo/demo_servers.py``), and wait in
real time. With ``ROS_TUI_SHOTS=1`` each takes a shot of where it ends.

Manual checklist against the Docker demo playground (see docs/docker.md):

    ros2 launch ros_tui demo.launch.py turtlesim:=true   # shell 1: demo servers + turtlesim
    ros2 run ros_tui ros_tui                             # shell 2

  - The app starts in under 2 s and the ☰ list fills with the demo graph; tab cycles the chips.
  - / filters as you type and stays responsive; enter opens the match in a tab.
  - /counter (~50 Hz) opens in Echo: space echoes it, the count and Hz rise, the UI stays smooth;
    enter freezes the values, esc goes live again.
  - /add_two_ints: enter enter, type 19, tab, 23, esc, space: the response says sum: 42.
  - /fibonacci: send a goal (order 20) with space, watch the feedback grow, s cancels it (CANCELED).
    /turtle1/rotate_absolute (theta: 1.57) turns the turtle.
  - /turtle1/cmd_vel (geometry_msgs/Twist) opens in Publish with its fields unfolded; f on a
    field with a helper opens it.
  - r repeats /turtle1/cmd_vel at 10 Hz (linear.x: 1.0): the turtle drives. :q quits, and the
    repeat stops (ros2 topic hz /turtle1/cmd_vel in another shell goes quiet): the turtle stops.
  - A goal still running when you quit is canceled.
  - A node (/ros_tui_demo_servers): its interfaces and parameters load; change publish_rate
    and set it with space.
"""

import time

import pytest
from conftest import ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, FIBONACCI_ACTION, INBOX_TOPIC
from harness.screens import ui_session

pytestmark = pytest.mark.e2e

FIXTURE_NODE = '/tui_test_fixtures'
GRAPH_TIMEOUT_S = 10.0


async def open_entry(s, kind: str, name: str, query: str, published: bool = False) -> None:
    """Wait until the graph lists `name` (and, if `published`, its publisher count arrived), then
    open it with / search."""
    def listed():
        item = next((item for item in s.app.nav.catalog[kind] if item.name == name), None)
        return item is not None and (item.publishers > 0 or not published)

    assert await s.wait_until(listed, timeout=GRAPH_TIMEOUT_S), f'{name} never appeared in {kind}'
    await s.keys('slash', *query, 'enter')
    assert s.state()['path'] == ['tabs', name], s.state()['path']


async def test_action_round_trip_through_ui(bridge, fixture_servers):
    async with ui_session(bridge=bridge) as s:
        await open_entry(s, 'actions', FIBONACCI_ACTION, 'fib')
        await s.keys('enter', 'enter', '6', 'escape', 'space')
        assert await s.wait_until(lambda: 'SUCCEEDED' in s.text(), timeout=15.0), s.text()
        assert 'sequence: [0, 1, 1, 2, 3, 5, 8]' in s.text()
        await s.shot('goal-succeeded', expect='RESULT ✓ SUCCEEDED with sequence: [0, 1, 1, 2, 3, 5, 8]')


async def test_service_round_trip_through_ui(bridge, fixture_servers):
    async with ui_session(bridge=bridge) as s:
        await open_entry(s, 'services', ADD_TWO_INTS_SERVICE, 'add')
        await s.keys('enter', 'enter', '1', '9', 'tab', '2', '3', 'escape', 'space')
        assert await s.wait_until(lambda: '✓ OK' in s.text(), timeout=10.0), s.text()
        assert 'sum: 42' in s.text()
        await s.shot('called', expect='RESPONSE ✓ OK with sum: 42')


async def test_topic_echo_and_publish_through_ui(bridge, fixture_servers):
    async with ui_session(bridge=bridge) as s:
        await open_entry(s, 'topics', CHATTER_TOPIC, 'chatter', published=True)
        assert s.app.nav.entry_mode() == 'echo'
        await s.keys('space')
        assert await s.wait_until(lambda: "'chatter " in s.text() and ' Hz' in s.text(), timeout=10.0), s.text()
        await s.shot('echo-live', expect="the echo of the 100 Hz chatter: N received · ~100 Hz, data 'chatter N'")
        await s.keys('space')  # Stop the echo.

        await open_entry(s, 'topics', INBOX_TOPIC, 'inbox')
        assert s.app.nav.entry_mode() == 'publish'
        await s.keys('enter', 'enter', *'fromtui', 'escape')
        deadline = time.monotonic() + 10.0
        while 'fromtui' not in fixture_servers.inbox_messages:
            await s.keys('space')  # Publish again until DDS discovery lets one through.
            await s.pilot.pause(0.2)
            assert time.monotonic() < deadline, 'the published message never arrived'


async def test_node_parameter_set_through_ui(bridge, fixture_servers):
    async with ui_session(bridge=bridge) as s:
        await open_entry(s, 'nodes', FIXTURE_NODE, 'fixtures')
        entry = s.app.nav.entry(s.app.nav.tab)

        def params():
            return entry.params

        assert await s.wait_until(params, timeout=GRAPH_TIMEOUT_S), 'the parameters never loaded'
        row = [param.name for param in params()].index('test_param')
        await s.keys('l', 'enter', *['j'] * row, 'c', '7', 'enter', 'space')
        node = fixture_servers.node
        assert await s.wait_until(lambda: node.get_parameter('test_param').value == 7, timeout=10.0)
        await s.shot('param-set', expect='PARAMETERS: test_param int 7, set on the node')
