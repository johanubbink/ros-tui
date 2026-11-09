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

"""The real RosBridge (no UI) over DDS, beyond the smoke tests in test_bridge.py: the offline tier.

CI leaves these out; scripts/agent_check.sh runs them (see docs/testing.md). Like every real-ROS test
they assert only outcomes that eventually arrive, never rates or how long something took.
"""

import threading
import time

import pytest
import rclpy
from conftest import (ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, EVENTUALLY_S, FIBONACCI_ACTION, FIXTURE_NODE,
                      INBOX_TOPIC, answer_of, event_kinds, listed_param, set_param, terminal_event, wait_for)
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from rcl_interfaces.srv import ListParameters
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from ros_tui.ros import bridge as bridge_module
from ros_tui.ros import inflight
from ros_tui.ros.bridge import RosBridge
from ros_tui.ros.events import ActionEventKind
from std_msgs.msg import String

pytestmark = [pytest.mark.ros_graph, pytest.mark.offline]

ADD_TWO_INTS_TYPE = 'example_interfaces/srv/AddTwoInts'
FIBONACCI_TYPE = 'example_interfaces/action/Fibonacci'
STRING_TYPE = 'std_msgs/msg/String'


def test_graph_listener_fires_with_increasing_versions(bridge, fixture_servers):
    seen_versions = []
    bridge.set_graph_listener(lambda snapshot: seen_versions.append(snapshot.version))
    topic_name = '/tui_listener_probe'
    bridge.publish_once(topic_name, STRING_TYPE, String(data='x')).result(timeout=EVENTUALLY_S)
    assert wait_for(lambda: any(entry.name == topic_name for entry in bridge.latest_graph.topics))
    assert wait_for(lambda: seen_versions)
    assert seen_versions == sorted(set(seen_versions)), 'versions must be strictly increasing'


def test_service_unavailable_times_out(bridge):
    future = bridge.call_service(
        '/tui_no_such_service', ADD_TWO_INTS_TYPE, AddTwoInts.Request(a=1, b=1)
    )
    with pytest.raises(TimeoutError, match='not available'):
        future.result(timeout=EVENTUALLY_S)


def test_more_parked_calls_than_the_client_cache_holds_each_time_out(bridge):
    """Every cached client is busy, so the cache grows instead of destroying a client a
    call still needs: each call ends with its own timeout."""
    futures = [
        bridge.call_service(f'/tui_missing_{index}', ADD_TWO_INTS_TYPE, AddTwoInts.Request())
        for index in range(10)
    ]
    for future in futures:
        with pytest.raises(TimeoutError, match='not available'):
            future.result(timeout=EVENTUALLY_S)


def test_action_cancel_midway(bridge, fixture_servers):
    events = []
    bridge.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=200), events.append)
    assert wait_for(lambda: ActionEventKind.FEEDBACK in event_kinds(events))
    bridge.cancel_goal(FIBONACCI_ACTION)
    assert wait_for(lambda: terminal_event(events))
    kinds = event_kinds(events)
    assert ActionEventKind.CANCEL_ACCEPTED in kinds
    from action_msgs.msg import GoalStatus

    assert terminal_event(events).status == GoalStatus.STATUS_CANCELED


def test_double_send_rejected_while_in_flight(bridge, fixture_servers):
    events = []
    second_events = []
    bridge.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=200), events.append)
    assert wait_for(lambda: ActionEventKind.ACCEPTED in event_kinds(events))
    bridge.send_goal(
        FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=3), second_events.append
    )
    assert wait_for(lambda: second_events)
    assert second_events[0].kind == ActionEventKind.ERROR
    assert 'already in flight' in second_events[0].payload
    bridge.cancel_goal(FIBONACCI_ACTION)
    assert wait_for(lambda: terminal_event(events))


def test_send_goal_to_missing_server_reports_error(bridge):
    events = []
    bridge.send_goal('/tui_no_such_action', FIBONACCI_TYPE, Fibonacci.Goal(order=3), events.append)
    assert wait_for(lambda: events)
    assert events[0].kind == ActionEventKind.ERROR
    assert 'not available' in events[0].payload


def test_publish_once_received_by_fixture(bridge, fixture_servers):
    fixture_servers.inbox_messages.clear()

    def published_and_received():
        # A message published before discovery matched the fixture's subscription is lost: publish
        # again until one arrives.
        bridge.publish_once(INBOX_TOPIC, STRING_TYPE, String(data='hello')).result(timeout=EVENTUALLY_S)
        return wait_for(lambda: 'hello' in fixture_servers.inbox_messages, timeout=0.5)

    assert wait_for(published_and_received), fixture_servers.inbox_messages


def wait_until_quiet(messages, quiet_s, timeout=EVENTUALLY_S):
    """True once no message has arrived in ``messages`` for ``quiet_s`` seconds."""
    deadline = time.monotonic() + timeout
    count, since = len(messages), time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.02)
        if len(messages) != count:
            count, since = len(messages), time.monotonic()
        elif time.monotonic() - since >= quiet_s:
            return True
    return False


def test_periodic_publish_reaches_the_node_until_shutdown(fixture_servers, ros_domain):
    own_bridge = RosBridge(node_name='ros_tui_shutdown_test')
    own_bridge.start()
    fixture_servers.inbox_messages.clear()
    own_bridge.start_periodic_publish(
        INBOX_TOPIC, STRING_TYPE, String(data='tick'), rate_hz=20.0
    ).result(timeout=EVENTUALLY_S)
    assert wait_for(lambda: len(fixture_servers.inbox_messages) >= 10), 'the periodic publish stopped early'
    own_bridge.shutdown()
    # Eventually a whole second passes without a message (never, at 20 Hz, while it still publishes).
    # The timer period, and that stop and shutdown destroy the timer, are in test_bridge.py.
    assert wait_until_quiet(fixture_servers.inbox_messages, quiet_s=1.0)


def test_bridge_shutdown_cancels_a_running_goal(fixture_servers, ros_domain):
    own_bridge = RosBridge(node_name='ros_tui_shutdown_goal_test')
    own_bridge.start()
    events = []
    own_bridge.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=200), events.append)
    assert wait_for(lambda: ActionEventKind.FEEDBACK in event_kinds(events))
    canceled_before = fixture_servers.canceled_goals
    own_bridge.shutdown()
    assert wait_for(lambda: not own_bridge._thread.is_alive()), 'the ROS thread never ended'
    assert wait_for(lambda: fixture_servers.canceled_goals == canceled_before + 1)


def test_get_node_info_lists_node_endpoints(peer, fixture_servers):
    def names(entries):
        return {entry.name for entry in entries}

    def discovered():
        # Until the bridge has discovered the fixture node, get_*_by_node raises
        # "nonexistent node" and get_node_info reports it as an error: keep polling.
        info, _error = answer_of(peer.get_node_info, FIXTURE_NODE) or (None, None)
        if info is None:
            return None
        ready = (
            CHATTER_TOPIC in names(info.publishers)
            and INBOX_TOPIC in names(info.subscribers)
            and ADD_TWO_INTS_SERVICE in names(info.service_servers)
            and FIBONACCI_ACTION in names(info.action_servers)
        )
        return info if ready else None

    info = wait_for(discovered)
    assert info is not None, f'fixture node endpoints were not discovered: {answer_of(peer.get_node_info, FIXTURE_NODE)}'
    assert info.node_name == FIXTURE_NODE
    # The fixture node's own parameter services are hidden, as the ☰ list hides them.
    assert not any(name.endswith('/get_parameters') for name in names(info.service_servers))
    # No hidden action-internal endpoints leak into the topic/service lists.
    leaked = names(info.publishers) | names(info.subscribers) | names(info.service_servers)
    assert not any('/_' in name for name in leaked), leaked


# ---------------------------------------------------------------- parameters


@pytest.mark.parametrize('name, type_label, sent, declared, received', [
    ('test_doubles', 'double[]', [1, 2], [0.5], [1.0, 2.0]),  # Whole numbers, sent as doubles.
    ('test_doubles', 'double[]', [], [0.5], []),
    ('test_names', 'string[]', [], ['a'], []),
])
def test_set_an_array_parameter_by_its_declared_type(peer, fixture_servers, name, type_label, sent, declared, received):
    node = fixture_servers.node
    assert wait_for(lambda: listed_param(peer, name) is not None)
    try:
        assert set_param(peer, name, sent, type_label) is None
        assert list(node.get_parameter(name).value) == received
        assert listed_param(peer, name) == received
    finally:
        node.set_parameters([Parameter(name, value=declared)])


@pytest.mark.parametrize('ask', [
    lambda bridge, node, on_done: bridge.list_node_parameters(node, on_done),
    lambda bridge, node, on_done: bridge.set_node_parameter(node, 'test_param', 0, 'int', on_done),
    lambda bridge, node, on_done: bridge.get_node_info(node, on_done),
], ids=['list', 'set', 'info'])
def test_a_node_request_callback_that_raises_is_not_called_again(peer, fixture_servers, ask):
    assert wait_for(lambda: listed_param(peer, 'test_param') is not None)
    calls = []

    def on_done(*answer):
        calls.append(answer)
        raise RuntimeError('a bug in the caller')

    ask(peer, FIXTURE_NODE, on_done)
    assert wait_for(lambda: calls)
    peer.submit(lambda: None).result(timeout=EVENTUALLY_S)  # The ROS thread is past the reply's handler.
    assert len(calls) == 1 and calls[0][-1] is None, calls  # Answered once, without an error.


def test_set_unknown_node_parameter_reports_error(peer, fixture_servers):
    assert set_param(peer, 'no_such_param', 1, 'int') is not None  # The node rejects an undeclared parameter.


# ---------------------------------------------------------------- servers that hold a request

HELD_NODE = '/tui_held'
HELD_ACTION = '/tui_held_goal'


class HeldServers:
    """A parameter list service and an action server that each hold a request until released."""

    def __init__(self, context):
        self.node = rclpy.create_node('tui_held_servers', context=context)
        self.list_received, self.release_list, self.list_answered = threading.Event(), threading.Event(), threading.Event()
        self.goal_received, self.release_goal = threading.Event(), threading.Event()
        self.cancel_requests = 0
        group = ReentrantCallbackGroup()
        self.node.create_service(ListParameters, f'{HELD_NODE}/list_parameters', self._list,
                                 callback_group=group)
        self.action_server = ActionServer(
            self.node, Fibonacci, HELD_ACTION, execute_callback=self._execute,
            goal_callback=self._goal, cancel_callback=self._cancel, callback_group=group)

    def reset(self):
        for event in (self.list_received, self.release_list, self.list_answered, self.goal_received,
                      self.release_goal):
            event.clear()
        self.cancel_requests = 0

    def release_all(self):
        self.release_list.set()
        self.release_goal.set()

    def _list(self, request, response):
        self.list_received.set()
        self.release_list.wait(timeout=EVENTUALLY_S)
        self.list_answered.set()
        return response

    def _goal(self, goal_request):
        self.goal_received.set()
        self.release_goal.wait(timeout=EVENTUALLY_S)
        return GoalResponse.ACCEPT

    def _cancel(self, cancel_request):
        self.cancel_requests += 1
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        wait_for(lambda: goal_handle.is_cancel_requested, timeout=5.0)
        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
        else:
            goal_handle.succeed()
        return Fibonacci.Result()


@pytest.fixture(scope='module')
def held_node(ros_domain):
    # One node for the module, reset for each test: a node re-created under the same name is slow
    # to be discovered again.
    context = rclpy.Context()
    rclpy.init(context=context)
    servers = HeldServers(context)
    executor = MultiThreadedExecutor(num_threads=4, context=context)
    executor.add_node(servers.node)
    spin_thread = threading.Thread(target=executor.spin, name='held-spin', daemon=True)
    spin_thread.start()
    yield servers
    servers.release_all()
    executor.shutdown()
    spin_thread.join(timeout=3.0)
    servers.node.destroy_node()
    rclpy.shutdown(context=context)


@pytest.fixture
def held_servers(held_node):
    held_node.reset()
    yield held_node
    held_node.release_all()  # Let a request the test left held finish.


def list_held_params(bridge, held_servers):
    """Ask the held node for its parameters; returns the list the answers land in."""
    answers = []
    bridge.list_node_parameters(HELD_NODE, lambda params, error: answers.append((params, error)))
    assert held_servers.list_received.wait(timeout=EVENTUALLY_S)
    return answers


def test_shutdown_cancels_a_goal_accepted_after_a_parameter_reply_landed(bridge, held_servers, monkeypatch):
    """A parameter reply that lands while shutdown waits for the goals is ignored, so the wait
    goes on and the goal, accepted only then, is still canceled."""
    # Shutdown waits for a goal's acceptance only so long; here the test decides when it comes.
    monkeypatch.setattr(bridge_module, 'SHUTDOWN_CANCEL_TIMEOUT_S', EVENTUALLY_S)
    answers = list_held_params(bridge, held_servers)
    events = []
    bridge.send_goal(HELD_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=5), events.append)
    assert held_servers.goal_received.wait(timeout=EVENTUALLY_S)
    stopping = threading.Thread(target=bridge.shutdown, kwargs={'timeout_s': EVENTUALLY_S})
    stopping.start()
    # Shutdown fails the parameter request, then waits for the goal's acceptance to cancel it.
    assert wait_for(lambda: answers), 'shutdown never failed the parameter request'
    held_servers.release_list.set()
    assert held_servers.list_answered.wait(timeout=EVENTUALLY_S)  # Its reply is on the way.
    held_servers.release_goal.set()
    stopping.join(timeout=EVENTUALLY_S)
    assert wait_for(lambda: held_servers.cancel_requests == 1), event_kinds(events)
    assert answers == [(None, 'ROS bridge shut down')]  # The late reply was ignored.


def test_shutdown_fails_a_call_still_awaiting_its_response(bridge, held_servers):
    future = bridge.call_service(
        f'{HELD_NODE}/list_parameters', 'rcl_interfaces/srv/ListParameters', ListParameters.Request()
    )
    assert held_servers.list_received.wait(timeout=EVENTUALLY_S)
    bridge.shutdown()
    with pytest.raises(RuntimeError, match='ROS bridge shut down'):
        future.result(timeout=EVENTUALLY_S)


def test_a_parameter_request_without_a_response_times_out(bridge, held_servers, monkeypatch):
    monkeypatch.setattr(inflight, 'RESPONSE_TIMEOUT_S', 1.0)
    answers = list_held_params(bridge, held_servers)
    assert wait_for(lambda: answers)
    assert answers == [(None, f'no response from {HELD_NODE}/list_parameters after 1 s')]


def test_shutdown_fails_a_parameter_request_awaiting_its_response(bridge, held_servers):
    answers = list_held_params(bridge, held_servers)
    bridge.shutdown()
    assert answers == [(None, 'ROS bridge shut down')]


def test_a_parameter_reply_is_handled_once_the_bridge_refuses_new_commands(bridge, held_servers, monkeypatch):
    """A reply that lands after shutdown() began but before the ROS thread stopped spinning is
    handled where it lands: nothing raises in the spin loop, and on_done still runs."""
    answers = list_held_params(bridge, held_servers)

    def refuse(command):
        raise RuntimeError('ROS bridge is not running')

    monkeypatch.setattr(bridge, 'submit', refuse)  # What submit does once shutdown() began.
    held_servers.release_list.set()
    assert wait_for(lambda: answers)
    assert answers == [([], None)]  # The held node lists no parameters.
