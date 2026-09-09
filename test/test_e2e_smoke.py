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
Full-stack smoke: real RosBridge + real fixture servers + the real app under Pilot.

The automated tests below drive the real app against the in-process fixture servers
(``test/conftest.py``), which mirror the demo node in ``ros_tui/demo/demo_servers.py``.

Manual checklist against the Docker demo playground (run in two shells inside the dev
container — see the README "Try it in Docker"):

    ros2 launch ros_tui demo.launch.py turtlesim:=true   # demo servers + turtlesim
    ros2 run ros_tui ros_tui

  - App starts < 2 s and all four tabs populate with the demo graph.
  - Filter stays responsive while typing.
  - Echo a high-rate topic (/counter @ ~50 Hz): stats line shows Hz, drops counted,
    UI stays smooth; best-effort publishers are received (QoS adaptation).
  - Send a goal on an action (/fibonacci order: 20, or /turtle1/rotate_absolute
    theta: 1.57), watch feedback, cancel it; status line ends CANCELED.
  - Call a service (/add_two_ints, or /spawn) and check the response renders.
  - Select a nested message type (/turtle1/cmd_vel — geometry_msgs/Twist): editor
    seeds defaults and round-trips.
  - Start a 10 Hz publisher on /turtle1/cmd_vel, quit with ctrl+q, verify it stops
    (ros2 topic hz /turtle1/cmd_vel in shell 2) — and the turtle stops moving.
"""

import time

import pytest
from conftest import ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, FIBONACCI_ACTION, INBOX_TOPIC
from ros_tui.ui.app import RosTuiApp
from test_ui_pilot import (
    click_button,
    log_text,
    select_entry,
    select_topic,
    show_tab,
    static_text,
    wait_until,
)
from textual.widgets import Button, Static, TextArea

pytestmark = pytest.mark.e2e


async def wait_for_entry(pilot, bridge, group, name, timeout=10.0):
    """Wait until the live graph lists ``name`` and return its InterfaceEntry."""

    def find():
        return next(
            (entry for entry in getattr(bridge.latest_graph, group) if entry.name == name), None
        )

    assert await wait_until(pilot, find, timeout=timeout), f'{name} never appeared in {group}'
    return find()


async def test_action_round_trip_through_ui(bridge, fixture_servers):
    app = RosTuiApp(bridge)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'actions')
        entry = await wait_for_entry(pilot, bridge, 'actions', FIBONACCI_ACTION)
        tab = app.query_one('#actions-tab')
        await select_entry(pilot, tab, entry)
        tab.query_one('#editor', TextArea).load_text('order: 6')
        tab.primary_action()
        status = tab.query_one('#goal-status', Static)
        assert await wait_until(pilot, lambda: 'SUCCEEDED' in static_text(status), timeout=15.0), (
            f'goal did not succeed; status: {static_text(status)}; log: {log_text(tab)}'
        )
        assert 'result: SUCCEEDED' in log_text(tab)
        assert '- 8' in log_text(tab)  # fib(6) sequence ends ... 5, 8


async def test_service_round_trip_through_ui(bridge, fixture_servers):
    app = RosTuiApp(bridge)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'services')
        entry = await wait_for_entry(pilot, bridge, 'services', ADD_TWO_INTS_SERVICE)
        tab = app.query_one('#services-tab')
        await select_entry(pilot, tab, entry)
        tab.query_one('#editor', TextArea).load_text('a: 19\nb: 23')
        tab.primary_action()
        assert await wait_until(
            pilot,
            lambda: not tab.query_one('#call-button', Button).disabled,
            timeout=10.0,
        )
        assert 'sum: 42' in log_text(tab)


async def test_topic_echo_and_publish_through_ui(bridge, fixture_servers):
    app = RosTuiApp(bridge)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')

        chatter = await wait_for_entry(pilot, bridge, 'topics', CHATTER_TOPIC)
        await select_topic(pilot, tab, chatter, 'subscribe')
        await click_button(pilot, '#echo-button')
        status = tab.query_one('#topics-status', Static)
        assert await wait_until(
            pilot,
            lambda: 'Hz' in static_text(status) and 'chatter' in log_text(tab),
            timeout=10.0,
        )
        await click_button(pilot, '#echo-button')  # Stop so the log quiets down.

        inbox = await wait_for_entry(pilot, bridge, 'topics', INBOX_TOPIC)
        await select_topic(pilot, tab, inbox, 'publish')
        tab.query_one('#editor', TextArea).load_text('data: from_the_tui')
        deadline = time.monotonic() + 10.0
        while 'from_the_tui' not in fixture_servers.inbox_messages:
            tab.primary_action()  # Re-publish until DDS discovery lets one through.
            await pilot.pause(0.2)
            assert time.monotonic() < deadline, 'published message never arrived'
