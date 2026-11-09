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

import time

import pytest
from conftest import (ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, EVENTUALLY_S, FIBONACCI_ACTION, FIXTURE_NODE,
                      INBOX_TOPIC, answer_of, event_kinds, terminal_event, wait_for)
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
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


def test_lru_overflow_with_pending_clients_does_not_crash(bridge):
    futures = [
        bridge.call_service(f'/tui_missing_{index}', ADD_TWO_INTS_TYPE, AddTwoInts.Request())
        for index in range(10)
    ]
    for future in futures:
        with pytest.raises((TimeoutError, RuntimeError)):
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


def test_get_node_info_lists_node_endpoints(bridge, fixture_servers):
    def names(entries):
        return {entry.name for entry in entries}

    def discovered():
        # Until the bridge has discovered the fixture node, get_*_by_node raises
        # "nonexistent node" and get_node_info reports it as an error: keep polling.
        info, _error = answer_of(bridge.get_node_info, FIXTURE_NODE) or (None, None)
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
    assert info is not None, f'fixture node endpoints were not discovered: {answer_of(bridge.get_node_info, FIXTURE_NODE)}'
    assert info.node_name == FIXTURE_NODE
    # The fixture node's own parameter services are hidden, as the ☰ list hides them.
    assert not any(name.endswith('/get_parameters') for name in names(info.service_servers))
    # No hidden action-internal endpoints leak into the topic/service lists.
    leaked = names(info.publishers) | names(info.subscribers) | names(info.service_servers)
    assert not any('/_' in name for name in leaked), leaked


def test_set_unknown_node_parameter_reports_error(bridge, fixture_servers):
    answer = answer_of(bridge.set_node_parameter, FIXTURE_NODE, 'no_such_param', '1')
    assert answer is not None, 'set_node_parameter never completed'
    assert answer[0] is not None  # An undeclared parameter is rejected by the node.
