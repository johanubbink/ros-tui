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

"""Headless UI tests: drive the textual app with Pilot against a FakeBridge (no rclpy)."""

import time
from concurrent.futures import Future

import pytest
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from ros_tui.ros.events import ActionEvent, ActionEventKind
from ros_tui.ros.graph import GraphSnapshot, InterfaceEntry
from ros_tui.ui.app import RosTuiApp
from ros_tui.ui.filterable_list import FilterableList
from textual.widgets import Button, Input, OptionList, RichLog, Static, TextArea

pytestmark = pytest.mark.ui

FIBONACCI_ENTRY = InterfaceEntry('/fibonacci', ('example_interfaces/action/Fibonacci',))
ADD_TWO_INTS_ENTRY = InterfaceEntry('/add_two_ints', ('example_interfaces/srv/AddTwoInts',))
CHATTER_ENTRY = InterfaceEntry('/chatter', ('std_msgs/msg/String',))
POSE_ENTRY = InterfaceEntry('/pose', ('geometry_msgs/msg/PoseStamped',))

SNAPSHOT = GraphSnapshot(
    version=1,
    actions=(FIBONACCI_ENTRY,),
    services=(ADD_TWO_INTS_ENTRY, InterfaceEntry('/set_bool', ('std_srvs/srv/SetBool',))),
    topics=(CHATTER_ENTRY, POSE_ENTRY),
    nodes=(),
)


def completed_future(result=None):
    future = Future()
    future.set_result(result)
    return future


class FakeBridge:
    def __init__(self, snapshot=SNAPSHOT):
        self.latest_graph = snapshot
        self.listener = None
        self.service_calls = []
        self.service_future = None
        self.sent_goals = []
        self.on_event = None
        self.cancelled = []
        self.published = []
        self.periodic_started = []
        self.periodic_stopped = []
        self.subscriptions = {}

    def set_graph_listener(self, listener):
        self.listener = listener

    def call_service(self, name, type_name, request, time_setters=()):
        self.service_calls.append((name, type_name, request))
        self.service_future = Future()
        return self.service_future

    def send_goal(self, name, type_name, goal, on_event, time_setters=()):
        self.sent_goals.append((name, type_name, goal))
        self.on_event = on_event

    def cancel_goal(self, name):
        self.cancelled.append(name)

    def publish_once(self, name, type_name, message, time_setters=()):
        self.published.append((name, type_name, message))
        return completed_future()

    def start_periodic_publish(self, name, type_name, message, rate_hz, time_setters=()):
        self.periodic_started.append((name, rate_hz))
        return completed_future()

    def stop_periodic_publish(self, name):
        self.periodic_stopped.append(name)
        return completed_future()

    def subscribe(self, name, type_name, buffer):
        self.subscriptions[name] = buffer
        return completed_future()

    def unsubscribe(self, name):
        self.subscriptions.pop(name, None)
        return completed_future()

    def shutdown(self):
        pass


async def wait_until(pilot, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await pilot.pause(0.05)
    return predicate()


async def click_button(pilot, selector):
    """Click and wait out the press animation — Buttons swallow clicks while '-active'."""
    await pilot.click(selector)
    await pilot.pause(0.25)


async def select_entry(pilot, tab, entry):
    tab.post_message(FilterableList.Selected(entry))
    # Wait for PrototypeReady to land (seed cached), not just for editor text: a late
    # prototype would overwrite any text the test loads into the editor afterwards.
    assert await wait_until(pilot, lambda: entry.name in tab._seed_cache), (
        f'prototype never loaded for {entry.name}'
    )


def log_text(tab):
    log = tab.query_one('#output-log', RichLog)
    return '\n'.join(strip.text for strip in log.lines)


def static_text(widget):
    return str(widget.render())


def editor_error_text(tab):
    error_line = tab.query_one('#editor-error', Static)
    return static_text(error_line) if error_line.display else ''


async def test_tabs_show_entity_lists():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        actions_list = app.query_one('#actions-tab FilterableList OptionList', OptionList)
        assert actions_list.option_count == 1
        await pilot.press('ctrl+2')
        services_list = app.query_one('#services-tab FilterableList OptionList', OptionList)
        assert services_list.option_count == 2
        await pilot.press('ctrl+3')
        topics_list = app.query_one('#topics-tab FilterableList OptionList', OptionList)
        assert topics_list.option_count == 2


async def test_filter_narrows_list():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press('ctrl+3')
        tab = app.query_one('#topics-tab')
        tab.query_one('#filter-input', Input).value = 'chat'
        option_list = tab.query_one('#entity-list', OptionList)
        assert await wait_until(pilot, lambda: option_list.option_count == 1)
        assert option_list.get_option_at_index(0).id == '/chatter'


async def test_selecting_topic_seeds_editor_with_defaults():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press('ctrl+3')
        tab = app.query_one('#topics-tab')
        await select_entry(pilot, tab, POSE_ENTRY)
        editor_text = tab.query_one('#editor', TextArea).text
        assert 'orientation:' in editor_text
        assert 'w: 1.0' in editor_text


async def test_invalid_yaml_blocks_call_with_inline_error():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press('ctrl+2')
        tab = app.query_one('#services-tab')
        await select_entry(pilot, tab, ADD_TWO_INTS_ENTRY)
        tab.query_one('#editor', TextArea).load_text('a: [unclosed')
        tab.primary_action()
        await pilot.pause()
        assert fake.service_calls == []
        assert 'YAML error' in editor_error_text(tab)
        # Field-level error: right structure, wrong value type.
        tab.query_one('#editor', TextArea).load_text('a: notanint\nb: 0')
        tab.primary_action()
        await pilot.pause()
        assert fake.service_calls == []
        assert editor_error_text(tab).startswith('a:')


async def test_call_sends_request_and_renders_response():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press('ctrl+2')
        tab = app.query_one('#services-tab')
        await select_entry(pilot, tab, ADD_TWO_INTS_ENTRY)
        tab.query_one('#editor', TextArea).load_text('a: 2\nb: 3')
        tab.primary_action()
        await pilot.pause()
        assert len(fake.service_calls) == 1
        _, _, request = fake.service_calls[0]
        assert request.a == 2 and request.b == 3
        assert tab.query_one('#call-button', Button).disabled
        fake.service_future.set_result(AddTwoInts.Response(sum=5))
        assert await wait_until(pilot, lambda: not tab.query_one('#call-button', Button).disabled)
        assert 'response in' in log_text(tab)
        assert 'sum: 5' in log_text(tab)


async def test_action_goal_feedback_result_render():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = app.query_one('#actions-tab')
        await select_entry(pilot, tab, FIBONACCI_ENTRY)
        tab.query_one('#editor', TextArea).load_text('order: 3')
        tab.primary_action()
        await pilot.pause()
        assert len(fake.sent_goals) == 1
        assert fake.sent_goals[0][2].order == 3
        assert tab.query_one('#send-button', Button).disabled
        assert not tab.query_one('#cancel-button', Button).disabled

        fake.on_event(ActionEvent('/fibonacci', ActionEventKind.ACCEPTED))
        status = tab.query_one('#goal-status', Static)
        assert await wait_until(pilot, lambda: 'EXECUTING' in static_text(status))
        fake.on_event(
            ActionEvent(
                '/fibonacci',
                ActionEventKind.FEEDBACK,
                payload=Fibonacci.Feedback(sequence=[0, 1, 1]),
            )
        )
        from action_msgs.msg import GoalStatus

        fake.on_event(
            ActionEvent(
                '/fibonacci',
                ActionEventKind.RESULT,
                payload=Fibonacci.Result(sequence=[0, 1, 1, 2]),
                status=GoalStatus.STATUS_SUCCEEDED,
            )
        )
        assert await wait_until(pilot, lambda: 'SUCCEEDED' in static_text(status))
        assert 'result: SUCCEEDED' in log_text(tab)
        assert not tab.query_one('#send-button', Button).disabled
        assert tab.query_one('#cancel-button', Button).disabled


async def test_rate_validation_and_start_stop():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press('ctrl+3')
        tab = app.query_one('#topics-tab')
        await select_entry(pilot, tab, CHATTER_ENTRY)
        tab.query_one('#rate-input', Input).value = '99999'
        await click_button(pilot, '#rate-button')
        assert fake.periodic_started == []
        assert 'rate must be within' in editor_error_text(tab)
        tab.query_one('#rate-input', Input).value = '10'
        await click_button(pilot, '#rate-button')
        assert fake.periodic_started == [('/chatter', 10.0)]
        assert str(tab.query_one('#rate-button', Button).label) == 'Stop rate'
        await click_button(pilot, '#rate-button')
        assert fake.periodic_stopped == ['/chatter']
        assert str(tab.query_one('#rate-button', Button).label) == 'Start rate'


async def test_echo_toggle_subscribes_and_unsubscribes():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press('ctrl+3')
        tab = app.query_one('#topics-tab')
        await select_entry(pilot, tab, CHATTER_ENTRY)
        await click_button(pilot, '#echo-button')
        assert '/chatter' in fake.subscriptions
        from std_msgs.msg import String

        fake.subscriptions['/chatter'].push(String(data='hello there'))
        assert await wait_until(pilot, lambda: 'hello there' in log_text(tab))
        await click_button(pilot, '#echo-button')
        assert '/chatter' not in fake.subscriptions
