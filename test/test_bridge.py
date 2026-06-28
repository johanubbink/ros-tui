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

"""Integration tests: the real RosBridge against in-process fixture servers (no UI)."""

import threading
import time
from types import SimpleNamespace

import pytest
from conftest import ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, FIBONACCI_ACTION, INBOX_TOPIC, wait_for
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


def event_kinds(events):
    return [event.kind for event in events]


def terminal_event(events):
    return next((event for event in events if event.kind == ActionEventKind.RESULT), None)


def test_submit_runs_on_ros_thread(bridge):
    future = bridge.submit(lambda: threading.current_thread().name)
    assert future.result(timeout=2.0) == 'ros-bridge'


def test_submit_storm_all_resolve(bridge):
    futures = [bridge.submit(lambda value=value: value) for value in range(200)]
    assert [future.result(timeout=5.0) for future in futures] == list(range(200))


def test_submit_after_shutdown_raises(bridge):
    bridge.shutdown()
    with pytest.raises(RuntimeError, match='not running'):
        bridge.submit(lambda: None)


def test_shutdown_idempotent(bridge):
    bridge.shutdown()
    bridge.shutdown()


def test_start_twice_is_a_noop(bridge):
    bridge.start()
    assert bridge.submit(lambda: 'ok').result(timeout=2.0) == 'ok'


def test_graph_lists_fixture_entities(bridge, fixture_servers):
    def fixture_entities_visible():
        graph = bridge.latest_graph
        return (
            any(entry.name == FIBONACCI_ACTION for entry in graph.actions)
            and any(entry.name == ADD_TWO_INTS_SERVICE for entry in graph.services)
            and any(entry.name == CHATTER_TOPIC for entry in graph.topics)
        )

    assert wait_for(fixture_entities_visible)
    graph = bridge.latest_graph
    action = next(entry for entry in graph.actions if entry.name == FIBONACCI_ACTION)
    assert action.types == (FIBONACCI_TYPE,)
    service = next(entry for entry in graph.services if entry.name == ADD_TWO_INTS_SERVICE)
    assert service.types == (ADD_TWO_INTS_TYPE,)
    all_names = [
        entry.name for group in (graph.actions, graph.services, graph.topics) for entry in group
    ]
    assert not any('/_' in name for name in all_names), all_names


def test_graph_listener_fires_with_increasing_versions(bridge, fixture_servers):
    seen_versions = []
    bridge.set_graph_listener(lambda snapshot: seen_versions.append(snapshot.version))
    topic_name = '/tui_listener_probe'
    bridge.publish_once(topic_name, STRING_TYPE, String(data='x')).result(timeout=2.0)
    assert wait_for(lambda: any(entry.name == topic_name for entry in bridge.latest_graph.topics))
    assert wait_for(lambda: seen_versions)
    assert seen_versions == sorted(set(seen_versions)), 'versions must be strictly increasing'


def test_service_call_roundtrip(bridge, fixture_servers):
    future = bridge.call_service(
        ADD_TWO_INTS_SERVICE, ADD_TWO_INTS_TYPE, AddTwoInts.Request(a=2, b=3)
    )
    assert future.result(timeout=5.0).sum == 5


def test_service_unavailable_times_out(bridge):
    future = bridge.call_service(
        '/tui_no_such_service', ADD_TWO_INTS_TYPE, AddTwoInts.Request(a=1, b=1)
    )
    with pytest.raises(TimeoutError, match='not available'):
        future.result(timeout=8.0)


def test_lru_overflow_with_pending_clients_does_not_crash(bridge):
    futures = [
        bridge.call_service(f'/tui_missing_{index}', ADD_TWO_INTS_TYPE, AddTwoInts.Request())
        for index in range(10)
    ]
    for future in futures:
        with pytest.raises((TimeoutError, RuntimeError)):
            future.result(timeout=8.0)


def test_action_goal_feedback_result(bridge, fixture_servers):
    events = []
    bridge.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=5), events.append)
    assert wait_for(lambda: terminal_event(events), timeout=10.0), event_kinds(events)
    kinds = event_kinds(events)
    # Feedback may overtake the goal response on the wire, so only assert relative order.
    assert ActionEventKind.ACCEPTED in kinds
    assert kinds.index(ActionEventKind.ACCEPTED) < kinds.index(ActionEventKind.RESULT)
    assert ActionEventKind.FEEDBACK in kinds
    result_event = terminal_event(events)
    from action_msgs.msg import GoalStatus

    assert result_event.status == GoalStatus.STATUS_SUCCEEDED
    assert list(result_event.payload.sequence) == [0, 1, 1, 2, 3, 5]


def test_action_cancel_midway(bridge, fixture_servers):
    events = []
    bridge.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=200), events.append)
    assert wait_for(lambda: ActionEventKind.FEEDBACK in event_kinds(events), timeout=10.0)
    bridge.cancel_goal(FIBONACCI_ACTION)
    assert wait_for(lambda: terminal_event(events), timeout=10.0)
    kinds = event_kinds(events)
    assert ActionEventKind.CANCEL_ACCEPTED in kinds
    from action_msgs.msg import GoalStatus

    assert terminal_event(events).status == GoalStatus.STATUS_CANCELED


def test_double_send_rejected_while_in_flight(bridge, fixture_servers):
    events = []
    second_events = []
    bridge.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=200), events.append)
    assert wait_for(lambda: ActionEventKind.ACCEPTED in event_kinds(events), timeout=10.0)
    bridge.send_goal(
        FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=3), second_events.append
    )
    assert wait_for(lambda: second_events, timeout=5.0)
    assert second_events[0].kind == ActionEventKind.ERROR
    assert 'already in flight' in second_events[0].payload
    bridge.cancel_goal(FIBONACCI_ACTION)
    assert wait_for(lambda: terminal_event(events), timeout=10.0)


def test_send_goal_to_missing_server_reports_error(bridge):
    events = []
    bridge.send_goal('/tui_no_such_action', FIBONACCI_TYPE, Fibonacci.Goal(order=3), events.append)
    assert wait_for(lambda: events, timeout=8.0)
    assert events[0].kind == ActionEventKind.ERROR
    assert 'not available' in events[0].payload


def test_publish_once_received_by_fixture(bridge, fixture_servers):
    fixture_servers.inbox_messages.clear()

    def published_and_received():
        bridge.publish_once(INBOX_TOPIC, STRING_TYPE, String(data='hello')).result(timeout=2.0)
        time.sleep(0.05)
        return fixture_servers.inbox_messages

    assert wait_for(published_and_received)
    assert fixture_servers.inbox_messages[-1] == 'hello'


def test_periodic_publish_rate_then_stop(bridge, fixture_servers):
    fixture_servers.inbox_messages.clear()
    bridge.start_periodic_publish(
        INBOX_TOPIC, STRING_TYPE, String(data='tick'), rate_hz=20.0
    ).result(timeout=2.0)
    assert wait_for(lambda: fixture_servers.inbox_messages, timeout=5.0)
    assert bridge.periodic_topics() == (INBOX_TOPIC,)
    count_at_start = len(fixture_servers.inbox_messages)
    time.sleep(1.0)
    delta = len(fixture_servers.inbox_messages) - count_at_start
    # Generous bounds: the point is 'roughly 20 Hz', not precise scheduling under load.
    assert 10 <= delta <= 30, f'expected ~20 messages in 1 s, got {delta}'
    bridge.stop_periodic_publish(INBOX_TOPIC).result(timeout=2.0)
    assert bridge.periodic_topics() == ()
    time.sleep(0.3)  # Let in-flight messages land before sampling the settled count.
    settled_count = len(fixture_servers.inbox_messages)
    time.sleep(0.4)
    assert len(fixture_servers.inbox_messages) == settled_count


def test_bridge_shutdown_stops_periodic_publish(fixture_servers, ros_domain):
    own_bridge = RosBridge(node_name='ros_tui_shutdown_test')
    own_bridge.start()
    fixture_servers.inbox_messages.clear()
    own_bridge.start_periodic_publish(
        INBOX_TOPIC, STRING_TYPE, String(data='tick'), rate_hz=20.0
    ).result(timeout=2.0)
    assert wait_for(lambda: fixture_servers.inbox_messages, timeout=5.0)
    own_bridge.shutdown()
    settled_count = len(fixture_servers.inbox_messages)
    time.sleep(0.4)
    assert len(fixture_servers.inbox_messages) <= settled_count + 1


def test_subscribe_receives_chatter(bridge, fixture_servers):
    buffer = EchoBuffer()
    bridge.subscribe(CHATTER_TOPIC, STRING_TYPE, buffer).result(timeout=2.0)
    assert wait_for(lambda: buffer.drain()[1] >= 50, timeout=5.0)
    _, _, _, rate_hz = buffer.drain()
    assert 50.0 <= rate_hz <= 150.0


def test_unsubscribe_stops_delivery(bridge, fixture_servers):
    buffer = EchoBuffer()
    bridge.subscribe(CHATTER_TOPIC, STRING_TYPE, buffer).result(timeout=2.0)
    assert wait_for(lambda: buffer.drain()[1] > 0, timeout=5.0)
    bridge.unsubscribe(CHATTER_TOPIC).result(timeout=2.0)
    received_after_stop = buffer.drain()[1]
    time.sleep(0.3)
    assert buffer.drain()[1] == received_after_stop


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


def test_get_node_info_lists_node_endpoints(bridge, fixture_servers):
    node = fixture_servers.node
    full_name = f'{node.get_namespace().rstrip("/")}/{node.get_name()}'

    def fetch_info():
        holder = {}
        done = threading.Event()

        def on_done(info, error):
            holder['info'] = info
            holder['error'] = error
            done.set()

        bridge.get_node_info(full_name, on_done)
        done.wait(timeout=3.0)
        return holder.get('info'), holder.get('error')

    def names(entries):
        return {entry.name for entry in entries}

    def discovered():
        # Until the bridge has discovered the fixture node, get_*_by_node raises
        # "nonexistent node" and get_node_info reports it as an error — keep polling.
        info, _error = fetch_info()
        if info is None:
            return None
        ready = (
            CHATTER_TOPIC in names(info.publishers)
            and INBOX_TOPIC in names(info.subscribers)
            and ADD_TWO_INTS_SERVICE in names(info.service_servers)
            and FIBONACCI_ACTION in names(info.action_servers)
        )
        return info if ready else None

    info = wait_for(discovered, timeout=15.0)
    assert info is not None, f'fixture node endpoints were not discovered: {fetch_info()}'
    assert info.node_name == full_name
    assert CHATTER_TOPIC in names(info.publishers)
    assert INBOX_TOPIC in names(info.subscribers)
    assert ADD_TWO_INTS_SERVICE in names(info.service_servers)
    assert FIBONACCI_ACTION in names(info.action_servers)
    # The fixture node's own parameter services are hidden, like the Services tab does.
    assert not any(name.endswith('/get_parameters') for name in names(info.service_servers))
    # No hidden action-internal endpoints leak into the topic/service lists.
    leaked = names(info.publishers) | names(info.subscribers) | names(info.service_servers)
    assert not any('/_' in name for name in leaked), leaked


def test_list_and_set_node_parameters(bridge, fixture_servers):
    node = fixture_servers.node
    full_name = f'{node.get_namespace().rstrip("/")}/{node.get_name()}'

    def list_params():
        holder = {}
        done = threading.Event()

        def on_done(params, error):
            holder['params'], holder['error'] = params, error
            done.set()

        bridge.list_node_parameters(full_name, on_done)
        done.wait(timeout=5.0)
        return holder.get('params'), holder.get('error')

    def test_param_value():
        params, _error = list_params()
        if params is None:
            return None
        return next((value for name, _type, value in params if name == 'test_param'), None)

    # Poll until the node's parameter services are discovered and report the declared value.
    assert wait_for(lambda: test_param_value() == 0, timeout=15.0), (
        f'test_param never listed as 0: {list_params()}'
    )

    # Set it through the bridge and confirm success (no error string back).
    set_result = {}
    set_done = threading.Event()

    def on_set(error):
        set_result['error'] = error
        set_done.set()

    bridge.set_node_parameter(full_name, 'test_param', '42', on_set)
    assert set_done.wait(timeout=5.0), 'set_node_parameter never completed'
    assert set_result['error'] is None, set_result['error']

    # The new value round-trips through a fresh list/get.
    assert wait_for(lambda: test_param_value() == 42, timeout=10.0)


def test_set_unknown_node_parameter_reports_error(bridge, fixture_servers):
    node = fixture_servers.node
    full_name = f'{node.get_namespace().rstrip("/")}/{node.get_name()}'
    result = {}
    done = threading.Event()

    def on_set(error):
        result['error'] = error
        done.set()

    bridge.set_node_parameter(full_name, 'no_such_param', '1', on_set)
    assert done.wait(timeout=10.0), 'set_node_parameter never completed'
    assert result['error'] is not None  # undeclared parameter is rejected by the node.


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
    bridge.submit(lambda: bridge._call_then(client, object(), handled.append)).result(timeout=2.0)

    # While the response is pending, the client is busy and cannot be chosen as a victim.
    assert bridge.submit(lambda: bridge._client_in_use(key, client)).result(timeout=2.0) is True

    # The response lands: the client is released and the handler is re-submitted to run.
    bridge.submit(future.fire).result(timeout=2.0)
    assert bridge.submit(lambda: bridge._client_in_use(key, client)).result(timeout=2.0) is False
    assert wait_for(lambda: bool(handled), timeout=2.0), 'handle was never invoked'
