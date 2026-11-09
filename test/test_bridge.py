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

"""The real RosBridge (no UI), in the fast tier that CI runs on every distro.

Two kinds of test, both deterministic enough for CI:

- How the bridge drives rclpy, checked on the ROS thread without waiting on DDS: the command queue,
  the entities it creates and destroys, the housekeeping of parked and in-flight requests.
- A smoke test of each way it talks to other nodes over DDS (graph, service, publish, subscribe,
  action, parameters), against the fixture servers in conftest.py. They assert only outcomes that
  eventually arrive, so a slow machine makes them slower, never red.

The rest of the bridge's DDS behaviour is in test_bridge_offline.py (see docs/testing.md).
"""

import threading
from types import SimpleNamespace

import pytest
from conftest import (ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, EVENTUALLY_S, FIBONACCI_ACTION, FIXTURE_NODE,
                      INBOX_TOPIC, answer_of, event_kinds, listed_param, set_param, terminal_event, wait_for)
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from ros_tui.ros.bridge import RosBridge, adapted_qos
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.events import ActionEventKind
from std_msgs.msg import String

pytestmark = pytest.mark.ros_graph

ADD_TWO_INTS_TYPE = 'example_interfaces/srv/AddTwoInts'
FIBONACCI_TYPE = 'example_interfaces/action/Fibonacci'
STRING_TYPE = 'std_msgs/msg/String'


def on_ros_thread(bridge, fn):
    """Run `fn` on the bridge's ROS thread (the only one that may touch its entities)."""
    return bridge.submit(fn).result(timeout=EVENTUALLY_S)


# ---------------------------------------------------------------- the ROS thread and its entities

def test_submit_runs_on_ros_thread(bridge):
    future = bridge.submit(lambda: threading.current_thread().name)
    assert future.result(timeout=EVENTUALLY_S) == 'ros-bridge'


def test_submit_storm_all_resolve(bridge):
    futures = [bridge.submit(lambda value=value: value) for value in range(200)]
    assert [future.result(timeout=EVENTUALLY_S) for future in futures] == list(range(200))


def test_submit_after_shutdown_raises(bridge):
    bridge.shutdown()
    with pytest.raises(RuntimeError, match='not running'):
        bridge.submit(lambda: None)


def test_shutdown_idempotent(bridge):
    bridge.shutdown()
    bridge.shutdown()


def test_start_twice_is_a_noop(bridge):
    bridge.start()
    assert bridge.submit(lambda: 'ok').result(timeout=EVENTUALLY_S) == 'ok'


def test_periodic_publish_runs_a_timer_at_the_rate_until_stopped(bridge):
    def timer_of(name):
        periodic = bridge._entities.periodic.get(name)
        return periodic.timer if periodic else None

    def live_timers():
        return list(bridge._node.timers)

    bridge.start_periodic_publish(INBOX_TOPIC, STRING_TYPE, String(data='tick'), rate_hz=20.0).result(EVENTUALLY_S)
    first = on_ros_thread(bridge, lambda: timer_of(INBOX_TOPIC))
    assert first.timer_period_ns == 50_000_000
    # Starting again on the topic replaces the loop: the old timer is gone, the new one has the new rate.
    bridge.start_periodic_publish(INBOX_TOPIC, STRING_TYPE, String(data='tock'), rate_hz=4.0).result(EVENTUALLY_S)
    second = on_ros_thread(bridge, lambda: timer_of(INBOX_TOPIC))
    assert second.timer_period_ns == 250_000_000
    timers = on_ros_thread(bridge, live_timers)
    assert second in timers and first not in timers
    bridge.stop_periodic_publish(INBOX_TOPIC).result(EVENTUALLY_S)
    assert on_ros_thread(bridge, lambda: timer_of(INBOX_TOPIC)) is None
    assert second not in on_ros_thread(bridge, live_timers)


def test_shutdown_leaves_nothing_on_the_node(bridge):
    """Nothing the bridge made outlives it: no periodic publish, echo or graph poll keeps running."""
    bridge.start_periodic_publish(INBOX_TOPIC, STRING_TYPE, String(data='tick'), rate_hz=20.0).result(EVENTUALLY_S)
    bridge.subscribe(CHATTER_TOPIC, STRING_TYPE, EchoBuffer()).result(timeout=EVENTUALLY_S)
    bridge.shutdown()
    assert wait_for(lambda: not bridge._thread.is_alive()), 'the ROS thread never ended'
    node = bridge._node
    left = (list(node.timers), list(node.publishers), list(node.subscriptions), list(node.clients), list(node.guards))
    assert left == ([], [], [], [], []), left


def test_unsubscribe_destroys_the_subscription(bridge):
    def subscribed_topics():
        return [subscription.topic_name for subscription in bridge._node.subscriptions]

    bridge.subscribe(CHATTER_TOPIC, STRING_TYPE, EchoBuffer()).result(timeout=EVENTUALLY_S)
    bridge.subscribe(CHATTER_TOPIC, STRING_TYPE, EchoBuffer()).result(timeout=EVENTUALLY_S)  # Already on.
    assert on_ros_thread(bridge, subscribed_topics).count(CHATTER_TOPIC) == 1
    bridge.unsubscribe(CHATTER_TOPIC).result(timeout=EVENTUALLY_S)
    assert CHATTER_TOPIC not in on_ros_thread(bridge, subscribed_topics)


def test_adapted_qos_truth_table():
    def info(reliability, durability):
        return SimpleNamespace(
            qos_profile=QoSProfile(depth=1, reliability=reliability, durability=durability)
        )

    reliable_volatile = info(ReliabilityPolicy.RELIABLE, DurabilityPolicy.VOLATILE)
    best_effort = info(ReliabilityPolicy.BEST_EFFORT, DurabilityPolicy.VOLATILE)
    transient = info(ReliabilityPolicy.RELIABLE, DurabilityPolicy.TRANSIENT_LOCAL)

    default = adapted_qos([])
    assert default.reliability == ReliabilityPolicy.RELIABLE
    assert default.durability == DurabilityPolicy.VOLATILE

    assert adapted_qos([reliable_volatile, best_effort]).reliability == (
        ReliabilityPolicy.BEST_EFFORT
    )
    assert adapted_qos([reliable_volatile]).reliability == ReliabilityPolicy.RELIABLE
    assert adapted_qos([transient]).durability == DurabilityPolicy.TRANSIENT_LOCAL
    assert adapted_qos([transient, reliable_volatile]).durability == DurabilityPolicy.VOLATILE


# ---------------------------------------------------------------- smoke: talking to other nodes over DDS


def test_graph_lists_fixture_entities(peer, fixture_servers):
    def fixture_entities_visible():
        graph = peer.latest_graph
        return (
            any(entry.name == FIBONACCI_ACTION for entry in graph.actions)
            and any(entry.name == ADD_TWO_INTS_SERVICE for entry in graph.services)
            and any(entry.name == CHATTER_TOPIC for entry in graph.topics)
        )

    assert wait_for(fixture_entities_visible)
    graph = peer.latest_graph
    action = next(entry for entry in graph.actions if entry.name == FIBONACCI_ACTION)
    assert action.types == (FIBONACCI_TYPE,)
    service = next(entry for entry in graph.services if entry.name == ADD_TWO_INTS_SERVICE)
    assert service.types == (ADD_TWO_INTS_TYPE,)
    assert next(entry for entry in graph.topics if entry.name == CHATTER_TOPIC).publishers >= 1
    all_names = [
        entry.name for group in (graph.actions, graph.services, graph.topics) for entry in group
    ]
    assert not any('/_' in name for name in all_names), all_names


def test_service_call_roundtrip(peer, fixture_servers):
    future = peer.call_service(
        ADD_TWO_INTS_SERVICE, ADD_TWO_INTS_TYPE, AddTwoInts.Request(a=2, b=3)
    )
    assert future.result(timeout=EVENTUALLY_S).sum == 5


def test_publish_once_reaches_an_echo(peer):
    # A topic of its own: a publisher the session-wide peer keeps would change how the app opens a
    # fixture topic in the end-to-end tests.
    topic = '/tui_test_loopback'
    buffer = EchoBuffer()
    peer.subscribe(topic, STRING_TYPE, buffer).result(timeout=EVENTUALLY_S)
    received = []

    def published_and_received():
        # A message published before discovery matched the subscription is lost: publish again.
        peer.publish_once(topic, STRING_TYPE, String(data='hello')).result(timeout=EVENTUALLY_S)
        return wait_for(lambda: received.extend(buffer.drain()[0]) or received, timeout=0.5)

    assert wait_for(published_and_received)
    assert received[-1].data == 'hello'


def test_subscribe_receives_chatter(peer, fixture_servers):
    buffer = EchoBuffer()
    received = []
    peer.subscribe(CHATTER_TOPIC, STRING_TYPE, buffer).result(timeout=EVENTUALLY_S)
    assert wait_for(lambda: received.extend(buffer.drain()[0]) or len(received) >= 3)
    numbers = [int(message.data.removeprefix('chatter ')) for message in received]
    assert numbers == sorted(numbers), numbers  # In the order they were published.


def test_action_goal_feedback_result(peer, fixture_servers):
    events = []
    peer.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=5), events.append)
    assert wait_for(lambda: terminal_event(events)), event_kinds(events)
    kinds = event_kinds(events)
    # Feedback may overtake the goal response on the wire, so only assert relative order.
    assert ActionEventKind.ACCEPTED in kinds
    assert kinds.index(ActionEventKind.ACCEPTED) < kinds.index(ActionEventKind.RESULT)
    assert ActionEventKind.FEEDBACK in kinds
    result_event = terminal_event(events)
    from action_msgs.msg import GoalStatus

    assert result_event.status == GoalStatus.STATUS_SUCCEEDED
    assert list(result_event.payload.sequence) == [0, 1, 1, 2, 3, 5]


def test_list_and_set_node_parameters(peer, fixture_servers):
    declared = fixture_servers.node.get_parameter('test_param').value
    # Poll until the node's parameter services are discovered and report its value.
    assert wait_for(lambda: listed_param(peer, 'test_param') == declared), f'test_param never listed as {declared}'
    params, _error = answer_of(peer.list_node_parameters, FIXTURE_NODE)
    assert {(name, kind) for name, kind, _value in params} >= {
        ('test_param', 'int'), ('test_doubles', 'double[]'), ('test_names', 'string[]'),
    }
    # Set it and confirm success, then put the value back: fixture_servers lives for the whole run.
    try:
        assert set_param(peer, 'test_param', declared + 42, 'int') is None
        assert wait_for(lambda: listed_param(peer, 'test_param') == declared + 42)
    finally:
        set_param(peer, 'test_param', declared, 'int')
