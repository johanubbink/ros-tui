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
import rclpy
from conftest import ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, FIBONACCI_ACTION, INBOX_TOPIC, wait_for
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from rcl_interfaces.srv import ListParameters
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from ros_tui.ros import inflight
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
    assert next(entry for entry in graph.topics if entry.name == CHATTER_TOPIC).publishers >= 1
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


def test_more_parked_calls_than_the_client_cache_holds_each_time_out(bridge):
    """Every cached client is busy, so the cache grows instead of destroying a client a
    call still needs: each call ends with its own timeout."""
    futures = [
        bridge.call_service(f'/tui_missing_{index}', ADD_TWO_INTS_TYPE, AddTwoInts.Request())
        for index in range(10)
    ]
    for future in futures:
        with pytest.raises(TimeoutError, match='not available'):
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
    # A loaded machine only delivers late, never early: ten more messages must come (it keeps
    # publishing), and must take at least a quarter second (it isn't far faster than 20 Hz).
    target = len(fixture_servers.inbox_messages) + 10
    started = time.monotonic()
    assert wait_for(lambda: len(fixture_servers.inbox_messages) >= target, timeout=5.0)
    elapsed = time.monotonic() - started
    assert elapsed >= 0.25, f'10 messages in {elapsed:.2f} s: faster than 20 Hz'
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


def test_bridge_shutdown_cancels_a_running_goal(fixture_servers, ros_domain):
    own_bridge = RosBridge(node_name='ros_tui_shutdown_goal_test')
    own_bridge.start()
    events = []
    own_bridge.send_goal(FIBONACCI_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=200), events.append)
    assert wait_for(lambda: ActionEventKind.FEEDBACK in event_kinds(events), timeout=10.0)
    canceled_before = fixture_servers.canceled_goals
    started = time.monotonic()
    own_bridge.shutdown()
    assert time.monotonic() - started < 3.0
    assert wait_for(lambda: fixture_servers.canceled_goals == canceled_before + 1, timeout=5.0)


HELD_NODE = '/tui_held'
HELD_ACTION = '/tui_held_goal'


class HeldServers:
    """A parameter list service and an action server that each hold a request until released."""

    def __init__(self, context):
        self.node = rclpy.create_node('tui_held_servers', context=context)
        self.list_received, self.release_list = threading.Event(), threading.Event()
        self.goal_received, self.release_goal = threading.Event(), threading.Event()
        self.cancel_requests = 0
        group = ReentrantCallbackGroup()
        self.node.create_service(ListParameters, f'{HELD_NODE}/list_parameters', self._list,
                                 callback_group=group)
        self.action_server = ActionServer(
            self.node, Fibonacci, HELD_ACTION, execute_callback=self._execute,
            goal_callback=self._goal, cancel_callback=self._cancel, callback_group=group)

    def _list(self, request, response):
        self.list_received.set()
        self.release_list.wait(timeout=10.0)
        return response

    def _goal(self, goal_request):
        self.goal_received.set()
        self.release_goal.wait(timeout=10.0)
        return GoalResponse.ACCEPT

    def _cancel(self, cancel_request):
        self.cancel_requests += 1
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        deadline = time.monotonic() + 5.0
        while not goal_handle.is_cancel_requested and time.monotonic() < deadline:
            time.sleep(0.02)
        if goal_handle.is_cancel_requested:
            goal_handle.canceled()
        else:
            goal_handle.succeed()
        return Fibonacci.Result()


@pytest.fixture
def held_servers(ros_domain):
    context = rclpy.Context()
    rclpy.init(context=context)
    servers = HeldServers(context)
    executor = MultiThreadedExecutor(num_threads=4, context=context)
    executor.add_node(servers.node)
    spin_thread = threading.Thread(target=executor.spin, name='held-spin', daemon=True)
    spin_thread.start()
    yield servers
    servers.release_list.set()
    servers.release_goal.set()
    executor.shutdown()
    spin_thread.join(timeout=3.0)
    servers.node.destroy_node()
    rclpy.shutdown(context=context)


def test_shutdown_cancels_a_goal_accepted_after_a_parameter_reply_landed(held_servers):
    """A parameter reply that lands while shutdown waits for the goals is ignored, so the wait
    goes on and the goal, accepted only then, is still canceled."""
    own_bridge = RosBridge(node_name='ros_tui_held_test')
    own_bridge.start()
    try:
        own_bridge.list_node_parameters(HELD_NODE, lambda params, error: None)
        assert held_servers.list_received.wait(timeout=10.0)
        events = []
        own_bridge.send_goal(HELD_ACTION, FIBONACCI_TYPE, Fibonacci.Goal(order=5), events.append)
        assert held_servers.goal_received.wait(timeout=10.0)
        stopping = threading.Thread(target=own_bridge.shutdown, kwargs={'timeout_s': 5.0})
        stopping.start()
        time.sleep(0.3)  # The bridge is now waiting for its goal's acceptance to cancel it.
        held_servers.release_list.set()
        time.sleep(0.1)  # The parameter reply lands first.
        held_servers.release_goal.set()
        stopping.join(timeout=6.0)
        assert wait_for(lambda: held_servers.cancel_requests == 1, timeout=3.0), event_kinds(events)
    finally:
        own_bridge.shutdown()


def test_shutdown_fails_a_call_still_awaiting_its_response(held_servers):
    own_bridge = RosBridge(node_name='ros_tui_held_call_test')
    own_bridge.start()
    try:
        future = own_bridge.call_service(
            f'{HELD_NODE}/list_parameters', 'rcl_interfaces/srv/ListParameters', ListParameters.Request()
        )
        assert held_servers.list_received.wait(timeout=10.0)
    finally:
        own_bridge.shutdown()
    with pytest.raises(RuntimeError, match='ROS bridge shut down'):
        future.result(timeout=2.0)


@pytest.fixture
def held_bridge(held_servers):
    own_bridge = RosBridge(node_name='ros_tui_held_param_test')
    own_bridge.start()
    yield own_bridge
    own_bridge.shutdown()


def list_held_params(bridge, held_servers):
    """Ask the held node for its parameters; returns the list the answers land in."""
    answers = []
    bridge.list_node_parameters(HELD_NODE, lambda params, error: answers.append((params, error)))
    assert held_servers.list_received.wait(timeout=10.0)
    return answers


def test_a_parameter_request_without_a_response_times_out(held_bridge, held_servers, monkeypatch):
    monkeypatch.setattr(inflight, 'RESPONSE_TIMEOUT_S', 1.0)
    answers = list_held_params(held_bridge, held_servers)
    assert wait_for(lambda: answers, timeout=5.0)
    assert answers == [(None, f'no response from {HELD_NODE}/list_parameters after 1 s')]


def test_shutdown_fails_a_parameter_request_awaiting_its_response(held_bridge, held_servers):
    answers = list_held_params(held_bridge, held_servers)
    held_bridge.shutdown()
    assert answers == [(None, 'ROS bridge shut down')]


def test_a_parameter_reply_is_handled_once_the_bridge_refuses_new_commands(
    held_bridge, held_servers, monkeypatch,
):
    """A reply that lands after shutdown() began but before the ROS thread stopped spinning is
    handled where it lands: nothing raises in the spin loop, and on_done still runs."""
    answers = list_held_params(held_bridge, held_servers)

    def refuse(command):
        raise RuntimeError('ROS bridge is not running')

    monkeypatch.setattr(held_bridge, 'submit', refuse)  # What submit does once shutdown() began.
    held_servers.release_list.set()
    assert wait_for(lambda: answers, timeout=5.0)
    assert answers == [([], None)]  # The held node lists no parameters.


def test_subscribe_receives_chatter(bridge, fixture_servers):
    buffer = EchoBuffer()
    bridge.subscribe(CHATTER_TOPIC, STRING_TYPE, buffer).result(timeout=2.0)
    assert wait_for(lambda: buffer.drain()[1] >= 50, timeout=5.0)
    _, _, _, rate_hz = buffer.drain()
    # About 100 Hz. The rate is taken over the last arrivals, which bunch up on a loaded machine,
    # so the band is wide: it catches a rate that is missing or off by an order of magnitude.
    assert 30.0 <= rate_hz <= 300.0


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
    # The fixture node's own parameter services are hidden, as the ☰ list hides them.
    assert not any(name.endswith('/get_parameters') for name in names(info.service_servers))
    # No hidden action-internal endpoints leak into the topic/service lists.
    leaked = names(info.publishers) | names(info.subscribers) | names(info.service_servers)
    assert not any('/_' in name for name in leaked), leaked


def fixture_node_name(fixture_servers):
    node = fixture_servers.node
    return f'{node.get_namespace().rstrip("/")}/{node.get_name()}'


def list_params(bridge, node_name, timeout=5.0):
    """(params, error) from list_node_parameters, or (None, None) if it never answered."""
    holder = {}
    done = threading.Event()

    def on_done(params, error):
        holder['params'], holder['error'] = params, error
        done.set()

    bridge.list_node_parameters(node_name, on_done)
    done.wait(timeout=timeout)
    return holder.get('params'), holder.get('error')


def set_param(bridge, node_name, name, value, type_label):
    """The error set_node_parameter answered with (None when the node took the value)."""
    result = {}
    done = threading.Event()

    def on_set(error):
        result['error'] = error
        done.set()

    bridge.set_node_parameter(node_name, name, value, type_label, on_set)
    assert done.wait(timeout=10.0), 'set_node_parameter never completed'
    return result.get('error')


def param_value(bridge, node_name, name):
    params, _error = list_params(bridge, node_name)
    return next((value for listed, _type, value in params or () if listed == name), None)


def test_list_and_set_node_parameters(bridge, fixture_servers):
    full_name = fixture_node_name(fixture_servers)
    # Poll until the node's parameter services are discovered and report the declared value.
    assert wait_for(lambda: param_value(bridge, full_name, 'test_param') == 0, timeout=15.0), (
        f'test_param never listed as 0: {list_params(bridge, full_name)}'
    )
    params, _error = list_params(bridge, full_name)
    assert {(name, kind) for name, kind, _value in params} >= {
        ('test_param', 'int'), ('test_doubles', 'double[]'), ('test_names', 'string[]'),
    }
    # Set it through the bridge and confirm success (no error string back), then restore
    # the declared value — fixture_servers is module-scoped, so leaking 42 would make
    # order-dependent runs of sibling tests see the wrong value.
    try:
        assert set_param(bridge, full_name, 'test_param', 42, 'int') is None
        assert wait_for(lambda: param_value(bridge, full_name, 'test_param') == 42, timeout=10.0)
    finally:
        set_param(bridge, full_name, 'test_param', 0, 'int')


@pytest.mark.parametrize('name, type_label, sent, declared, received', [
    ('test_doubles', 'double[]', [1, 2], [0.5], [1.0, 2.0]),  # Whole numbers, sent as doubles.
    ('test_doubles', 'double[]', [], [0.5], []),
    ('test_names', 'string[]', [], ['a'], []),
])
def test_set_an_array_parameter_by_its_declared_type(
    bridge, fixture_servers, name, type_label, sent, declared, received,
):
    full_name = fixture_node_name(fixture_servers)
    node = fixture_servers.node
    assert wait_for(lambda: param_value(bridge, full_name, name) is not None, timeout=15.0)
    try:
        assert set_param(bridge, full_name, name, sent, type_label) is None
        assert list(node.get_parameter(name).value) == received
        assert param_value(bridge, full_name, name) == received
    finally:
        node.set_parameters([Parameter(name, value=declared)])


@pytest.mark.parametrize('ask', [
    lambda bridge, node, on_done: bridge.list_node_parameters(node, on_done),
    lambda bridge, node, on_done: bridge.set_node_parameter(node, 'test_param', 0, 'int', on_done),
    lambda bridge, node, on_done: bridge.get_node_info(node, on_done),
], ids=['list', 'set', 'info'])
def test_a_node_request_callback_that_raises_is_not_called_again(bridge, fixture_servers, ask):
    full_name = fixture_node_name(fixture_servers)
    assert wait_for(lambda: param_value(bridge, full_name, 'test_param') == 0, timeout=15.0)
    calls = []

    def on_done(*answer):
        calls.append(answer)
        raise RuntimeError('a bug in the caller')

    ask(bridge, full_name, on_done)
    assert wait_for(lambda: calls, timeout=10.0)
    bridge.submit(lambda: None).result(timeout=2.0)  # The ROS thread is past the reply's handler.
    assert len(calls) == 1 and calls[0][-1] is None, calls  # Answered once, without an error.


def test_set_unknown_node_parameter_reports_error(bridge, fixture_servers):
    # The undeclared parameter is rejected by the node.
    assert set_param(bridge, fixture_node_name(fixture_servers), 'no_such_param', 1, 'int') is not None
