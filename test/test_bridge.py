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
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from conftest import (ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, EVENTUALLY_S, FIBONACCI_ACTION, FIXTURE_NODE,
                      INBOX_TOPIC, answer_of, event_kinds, terminal_event, wait_for)
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from ros_tui.constants import READY_TIMEOUT_S
from ros_tui.ros.bridge import RosBridge, _ActiveGoal, _AwaitingResponse, _PendingReady, adapted_qos
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


class _FakeFuture:
    """A call_async future whose done callback fires only when the test triggers it."""

    def __init__(self):
        self._callback = None

    def add_done_callback(self, callback):
        self._callback = callback

    def fire(self):
        self._callback(self)


class _FakeClient:
    srv_name = '/fake/set_parameters'

    def __init__(self, future):
        self._future = future

    def call_async(self, _request):
        return self._future


def test_call_then_marks_client_in_use_until_response(bridge):
    """An in-flight parameter call keeps its client out of LRU eviction (regression).

    ``_call_then`` must register the client in ``awaiting_response`` so ``_client_in_use``
    reports it busy for the call's lifetime — otherwise ``_get_or_create`` could evict and
    ``destroy_client`` it mid-flight — then drop it once the response lands.
    """
    future = _FakeFuture()
    client = _FakeClient(future)
    key = (_FakeClient.srv_name, 'rcl_interfaces/srv/SetParameters')
    handled = []

    # Dispatch on the ROS thread, exactly as the real parameter paths do.
    bridge.submit(lambda: bridge._call_then(client, object(), handled.append)).result(timeout=EVENTUALLY_S)

    # While the response is pending, the client is busy and cannot be chosen as a victim.
    assert bridge.submit(lambda: bridge._client_in_use(key, client)).result(timeout=EVENTUALLY_S) is True

    # The response lands: the client is released and the handler is re-submitted to run.
    bridge.submit(future.fire).result(timeout=EVENTUALLY_S)
    assert bridge.submit(lambda: bridge._client_in_use(key, client)).result(timeout=EVENTUALLY_S) is False
    assert wait_for(lambda: bool(handled)), 'handle was never invoked'


def test_housekeeping_dispatches_fails_or_keeps_each_wait_for_a_server(bridge):
    seen = []

    def pending(label, is_ready, deadline):
        return _PendingReady(entity=object(), is_ready=is_ready, dispatch=lambda: seen.append((label, 'sent')),
                             fail=lambda error: seen.append((label, str(error))), deadline=deadline, label=label)

    def broken():
        raise RuntimeError('graph gone')

    now = time.monotonic()
    waits = [pending('/ready', lambda: True, now + 60), pending('/late', lambda: False, now - 1),
             pending('/broken', broken, now + 60), pending('/waiting', lambda: False, now + 60)]
    on_ros_thread(bridge, lambda: bridge._entities.pending_ready.extend(waits))
    on_ros_thread(bridge, bridge._tick_pending)
    left = on_ros_thread(bridge, lambda: [wait.label for wait in bridge._entities.pending_ready])
    on_ros_thread(bridge, lambda: bridge._entities.pending_ready.clear())
    assert seen == [('/ready', 'sent'), ('/late', '/late not available (no server found)'),
                    ('/broken', 'graph gone')]
    assert left == ['/waiting']


def test_housekeeping_ends_a_goal_whose_server_vanished(bridge):
    events = []

    def goal(server_up, lost_since=None):
        return _ActiveGoal(handle=None, on_event=events.append,
                           client=SimpleNamespace(server_is_ready=lambda: server_up), server_lost_since=lost_since)

    now = time.monotonic()
    gone, lost, back = goal(False, now - READY_TIMEOUT_S - 1), goal(False), goal(True, now)

    def track():
        bridge._entities.active_goals.update({'/gone': gone, '/lost': lost, '/back': back})
        bridge._entities.inflight_actions.add('/gone')

    on_ros_thread(bridge, track)
    on_ros_thread(bridge, bridge._tick_pending)
    goals = on_ros_thread(bridge, lambda: sorted(bridge._entities.active_goals))
    inflight = on_ros_thread(bridge, lambda: set(bridge._entities.inflight_actions))
    on_ros_thread(bridge, lambda: bridge._entities.active_goals.clear())
    assert goals == ['/back', '/lost'] and '/gone' not in inflight
    assert [(event.action_name, event.kind, event.payload) for event in events] == [
        ('/gone', ActionEventKind.ERROR, 'action server vanished while the goal was executing')]
    assert lost.server_lost_since is not None and back.server_lost_since is None


def test_housekeeping_times_out_a_request_without_response(bridge):
    dropped = []
    client = SimpleNamespace(remove_pending_request=dropped.append)
    now = time.monotonic()
    late = _AwaitingResponse(client, 'late future', now - 1, '/slow', Future())
    untracked = _AwaitingResponse(client, 'parameter future', now - 1, '/param')  # No caller future.
    fine = _AwaitingResponse(client, 'fine future', now + 60, '/fine', Future())
    on_ros_thread(bridge, lambda: bridge._entities.awaiting_response.extend([late, untracked, fine]))
    on_ros_thread(bridge, bridge._tick_pending)
    left = on_ros_thread(bridge, lambda: list(bridge._entities.awaiting_response))
    on_ros_thread(bridge, lambda: bridge._entities.awaiting_response.clear())
    assert left == [fine] and dropped == ['late future', 'parameter future']
    with pytest.raises(TimeoutError, match='no response from /slow after 30 s'):
        late.outer.result(timeout=0)
    assert not fine.outer.done()


def test_shutdown_fails_every_request_still_awaiting_its_response(bridge):
    client = SimpleNamespace(remove_pending_request=lambda future: None)
    later = time.monotonic() + 60
    untracked = _AwaitingResponse(client, 'parameter future', later, '/param')  # No caller future.
    tracked = _AwaitingResponse(client, 'call future', later, '/call', Future())
    on_ros_thread(bridge, lambda: bridge._entities.awaiting_response.extend([untracked, tracked]))
    bridge.shutdown()
    with pytest.raises(RuntimeError, match='ROS bridge shut down'):
        tracked.outer.result(timeout=EVENTUALLY_S)


# ---------------------------------------------------------------- smoke: talking to other nodes over DDS


@pytest.fixture(scope='module')
def peer(ros_domain, fixture_servers):
    """One bridge for all the smoke tests: DDS discovery of a new node takes seconds, so pay it once."""
    ros_bridge = RosBridge(node_name='ros_tui_smoke')
    ros_bridge.start()
    yield ros_bridge
    ros_bridge.shutdown()


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


def test_publish_once_received_by_fixture(peer, fixture_servers):
    fixture_servers.inbox_messages.clear()

    def published_and_received():
        # A message published before discovery matched the fixture's subscription is lost: publish
        # again until one arrives.
        peer.publish_once(INBOX_TOPIC, STRING_TYPE, String(data='hello')).result(timeout=EVENTUALLY_S)
        return wait_for(lambda: 'hello' in fixture_servers.inbox_messages, timeout=0.5)

    assert wait_for(published_and_received), fixture_servers.inbox_messages


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

    def test_param_value():
        params, _error = answer_of(peer.list_node_parameters, FIXTURE_NODE) or (None, None)
        return next((value for name, _type, value in params or () if name == 'test_param'), None)

    def set_param(value):
        answer = answer_of(peer.set_node_parameter, FIXTURE_NODE, 'test_param', str(value))
        assert answer is not None, 'set_node_parameter never completed'
        return answer[0]  # The error, None on success.

    # Poll until the node's parameter services are discovered and report its value.
    assert wait_for(lambda: test_param_value() == declared), f'test_param never listed as {declared}'
    # Set it and confirm success, then put the value back: fixture_servers lives for the whole run.
    try:
        assert set_param(declared + 42) is None
        assert wait_for(lambda: test_param_value() == declared + 42)
    finally:
        set_param(declared)
