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
Thread-confined rclpy bridge.

One dedicated thread owns a private rclpy context, the node, the executor and EVERY rclpy
entity. All entity lifecycle runs on that thread via a guard-condition-driven command queue,
because creating/destroying rclpy entities from a foreign thread races the executor's wait
set. Results come back through concurrent.futures.Future or plain callbacks invoked on the
ROS thread (callers must keep those callbacks cheap and thread-safe — e.g. textual's
``post_message``). Nothing in this module may import textual.
"""

import contextlib
import functools
import queue
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions

from ros_tui.constants import (
    CLIENT_CACHE_SIZE,
    DEFAULT_QOS_DEPTH,
    GRAPH_POLL_PERIOD_S,
    HOUSEKEEPING_PERIOD_S,
    READY_TIMEOUT_S,
    RESPONSE_TIMEOUT_S,
    SHUTDOWN_CANCEL_TIMEOUT_S,
)
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.events import ActionEvent, ActionEventKind
from ros_tui.ros.graph import EMPTY_GRAPH, GraphSnapshot, build_node_info, build_snapshot
from ros_tui.ros.message_yaml import TimeSetter, import_type

GraphListener = Callable[[GraphSnapshot], None]
ActionEventCallback = Callable[[ActionEvent], None]


@functools.lru_cache(maxsize=1)
def _parameter_type_readers() -> dict:
    """Map each rcl_interfaces ParameterType to its (type_label, ParameterValue attribute)."""
    from rcl_interfaces.msg import ParameterType  # noqa: PLC0415
    return {
        ParameterType.PARAMETER_BOOL: ('bool', 'bool_value'),
        ParameterType.PARAMETER_INTEGER: ('int', 'integer_value'),
        ParameterType.PARAMETER_DOUBLE: ('double', 'double_value'),
        ParameterType.PARAMETER_STRING: ('string', 'string_value'),
        ParameterType.PARAMETER_BYTE_ARRAY: ('byte[]', 'byte_array_value'),
        ParameterType.PARAMETER_BOOL_ARRAY: ('bool[]', 'bool_array_value'),
        ParameterType.PARAMETER_INTEGER_ARRAY: ('int[]', 'integer_array_value'),
        ParameterType.PARAMETER_DOUBLE_ARRAY: ('double[]', 'double_array_value'),
        ParameterType.PARAMETER_STRING_ARRAY: ('string[]', 'string_array_value'),
    }


def _extract_parameters(names: list, values: list) -> list:
    """Convert rcl_interfaces ParameterValue list into [(name, type_label, value)] tuples."""
    readers = _parameter_type_readers()
    result = []
    for name, pv in zip(names, values):
        type_label, attr = readers.get(pv.type, ('?', None))
        value = getattr(pv, attr) if attr else None
        if hasattr(value, 'tolist'):
            value = value.tolist()
        result.append((name, type_label, value))
    return result


def _python_to_parameter_value(py_value: Any) -> Any:
    from rcl_interfaces.msg import ParameterType, ParameterValue  # noqa: PLC0415
    pv = ParameterValue()
    if isinstance(py_value, bool):
        pv.type = ParameterType.PARAMETER_BOOL
        pv.bool_value = py_value
    elif isinstance(py_value, int):
        pv.type = ParameterType.PARAMETER_INTEGER
        pv.integer_value = py_value
    elif isinstance(py_value, float):
        pv.type = ParameterType.PARAMETER_DOUBLE
        pv.double_value = py_value
    elif isinstance(py_value, str):
        pv.type = ParameterType.PARAMETER_STRING
        pv.string_value = py_value
    elif isinstance(py_value, list) and py_value:
        first = py_value[0]
        if isinstance(first, bool):
            pv.type = ParameterType.PARAMETER_BOOL_ARRAY
            pv.bool_array_value = py_value
        elif isinstance(first, int):
            pv.type = ParameterType.PARAMETER_INTEGER_ARRAY
            pv.integer_array_value = py_value
        elif isinstance(first, float):
            pv.type = ParameterType.PARAMETER_DOUBLE_ARRAY
            pv.double_array_value = py_value
        elif isinstance(first, str):
            pv.type = ParameterType.PARAMETER_STRING_ARRAY
            pv.string_array_value = py_value
        else:
            raise ValueError(f'unsupported list element type: {type(first).__name__}')
    elif isinstance(py_value, list):
        raise ValueError('cannot infer type of empty list')
    else:
        raise ValueError(f'unsupported parameter type: {type(py_value).__name__}')
    return pv


def adapted_qos(endpoint_infos: list[Any]) -> QoSProfile:
    """
    QoS that can hear every publisher.

    Best-effort if any publisher is best-effort; transient-local only if all
    publishers are transient-local.
    """
    qos = QoSProfile(depth=DEFAULT_QOS_DEPTH)
    profiles = [info.qos_profile for info in endpoint_infos]
    if any(profile.reliability == ReliabilityPolicy.BEST_EFFORT for profile in profiles):
        qos.reliability = ReliabilityPolicy.BEST_EFFORT
    if profiles and all(
        profile.durability == DurabilityPolicy.TRANSIENT_LOCAL for profile in profiles
    ):
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
    return qos


@dataclass
class _PendingReady:
    """A client waiting for its server to appear, checked by the housekeeping timer."""

    entity: Any
    is_ready: Callable[[], bool]
    dispatch: Callable[[], None]
    fail: Callable[[Exception], None]
    deadline: float
    label: str


@dataclass
class _AwaitingResponse:
    """An in-flight service request with a response deadline.

    ``outer`` is the caller's Future for request/response calls; parameter calls
    (dispatched via ``_call_then``) track the client only — to keep it out of LRU
    eviction while in flight — and leave ``outer`` ``None``.
    """

    client: Any
    rclpy_future: Any
    deadline: float
    label: str
    outer: Future | None = None


@dataclass
class _ActiveGoal:
    handle: Any
    on_event: ActionEventCallback
    client: Any
    server_lost_since: float | None = None  # When server_is_ready first turned false.


@dataclass
class _PeriodicPublish:
    timer: Any
    publisher_key: tuple[str, str]


@dataclass
class _Entities:
    """All ROS-thread-only mutable state, grouped so the ownership rule is visible."""

    clients: OrderedDict = field(default_factory=OrderedDict)
    action_clients: OrderedDict = field(default_factory=OrderedDict)
    publishers: OrderedDict = field(default_factory=OrderedDict)
    subscriptions: dict = field(default_factory=dict)
    periodic: dict = field(default_factory=dict)
    pending_ready: list = field(default_factory=list)
    awaiting_response: list = field(default_factory=list)
    active_goals: dict = field(default_factory=dict)
    inflight_actions: set = field(default_factory=set)


class RosBridge:
    """UI-agnostic facade over one rclpy node spun on a dedicated thread."""

    def __init__(self, node_name: str = 'ros_tui'):
        self._node_name = node_name
        self._running = False
        self._submit_lock = threading.Lock()
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._commands: queue.SimpleQueue = queue.SimpleQueue()
        self._context = None
        self._node = None
        self._executor = None
        self._guard = None
        self._latest_graph: GraphSnapshot = EMPTY_GRAPH
        self._graph_listener: GraphListener | None = None
        self._entities = _Entities()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._ros_main, name='ros-bridge', daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            self._running = False
            raise RuntimeError('ROS bridge did not start within 5 s')
        if self._startup_error is not None:
            self._running = False
            self._thread.join(timeout=1.0)
            raise RuntimeError(f'ROS bridge failed to start: {self._startup_error}')

    def shutdown(self, timeout_s: float = 3.0) -> None:
        with self._submit_lock:
            was_running = self._running
            self._running = False
        if was_running and self._guard is not None:
            with contextlib.suppress(Exception):
                self._guard.trigger()
        if self._thread is not None:
            self._thread.join(timeout_s)

    def submit(self, command: Callable[[], Any]) -> Future:
        """Run ``command`` on the ROS thread; its return/raise lands in the Future."""
        future: Future = Future()
        with self._submit_lock:
            if not self._running:
                raise RuntimeError('ROS bridge is not running')
            self._commands.put((command, future))
            self._guard.trigger()
        return future

    def now(self) -> float:
        """The UI's clock (seconds, monotonic). FakeBridge's ManualClock stands in for it in tests."""
        return time.monotonic()

    @property
    def latest_graph(self) -> GraphSnapshot:
        return self._latest_graph  # Atomic attribute read; safe from any thread.

    def set_graph_listener(self, listener: GraphListener | None) -> None:
        self._graph_listener = listener

    # ---------------------------------------------------------------- services

    def call_service(
        self,
        name: str,
        type_name: str,
        request: Any,
        time_setters: tuple[TimeSetter, ...] = (),
    ) -> Future:
        """Resolve with the response message; TimeoutError if no server or no response."""
        outer: Future = Future()
        command_future = self.submit(
            self._guarded(outer, self._start_service_call, name, type_name, request, time_setters)
        )

        def propagate_cancellation(done: Future) -> None:
            if done.cancelled() and not outer.done():
                outer.set_exception(RuntimeError('ROS bridge shut down'))

        command_future.add_done_callback(propagate_cancellation)
        return outer

    def _start_service_call(
        self,
        name: str,
        type_name: str,
        request: Any,
        time_setters: tuple[TimeSetter, ...],
        outer: Future,
    ) -> None:
        client = self._get_client(name, type_name)
        dispatch = functools.partial(
            self._dispatch_service, client, request, outer, name, time_setters
        )
        self._dispatch_or_wait(client, client.service_is_ready, dispatch, outer.set_exception, name)

    def _dispatch_service(
        self,
        client: Any,
        request: Any,
        outer: Future,
        name: str,
        time_setters: tuple[TimeSetter, ...],
    ) -> None:
        self._apply_time_setters(time_setters)
        rclpy_future = client.call_async(request)
        record = _AwaitingResponse(
            client=client,
            rclpy_future=rclpy_future,
            outer=outer,
            deadline=time.monotonic() + RESPONSE_TIMEOUT_S,
            label=name,
        )
        self._entities.awaiting_response.append(record)

        def on_done(done_future: Any) -> None:
            with contextlib.suppress(ValueError):
                self._entities.awaiting_response.remove(record)
            if outer.done():
                return
            error = done_future.exception()
            if error is not None:
                outer.set_exception(error)
            else:
                outer.set_result(done_future.result())

        rclpy_future.add_done_callback(on_done)

    # ---------------------------------------------------------------- actions

    def send_goal(
        self,
        name: str,
        type_name: str,
        goal: Any,
        on_event: ActionEventCallback,
        time_setters: tuple[TimeSetter, ...] = (),
    ) -> None:
        """Send a goal; the whole lifecycle is reported through ``on_event`` (ROS thread)."""

        def command() -> None:
            try:
                self._start_send_goal(name, type_name, goal, on_event, time_setters)
            except Exception as error:
                on_event(ActionEvent(name, ActionEventKind.ERROR, payload=str(error)))

        self.submit(command)

    def cancel_goal(self, name: str) -> None:
        """Request cancellation of the active goal on ``name``; no-op if there is none."""

        def command() -> None:
            active = self._entities.active_goals.get(name)
            if active is None:
                return
            cancel_future = active.handle.cancel_goal_async()

            def on_cancel(done_future: Any) -> None:
                try:
                    response = done_future.result()
                except Exception as error:
                    active.on_event(ActionEvent(name, ActionEventKind.ERROR, payload=str(error)))
                    return
                kind = (
                    ActionEventKind.CANCEL_ACCEPTED
                    if response.goals_canceling
                    else ActionEventKind.CANCEL_REJECTED
                )
                active.on_event(ActionEvent(name, kind))

            cancel_future.add_done_callback(on_cancel)

        self.submit(command)

    def _start_send_goal(
        self,
        name: str,
        type_name: str,
        goal: Any,
        on_event: ActionEventCallback,
        time_setters: tuple[TimeSetter, ...],
    ) -> None:
        if name in self._entities.inflight_actions:
            on_event(ActionEvent(name, ActionEventKind.ERROR, payload='goal already in flight'))
            return
        client = self._get_action_client(name, type_name)
        self._entities.inflight_actions.add(name)
        dispatch = functools.partial(
            self._dispatch_goal, client, name, goal, on_event, time_setters
        )

        def fail(error: Exception) -> None:
            self._entities.inflight_actions.discard(name)
            on_event(ActionEvent(name, ActionEventKind.ERROR, payload=str(error)))

        self._dispatch_or_wait(client, client.server_is_ready, dispatch, fail, name)

    def _dispatch_goal(
        self,
        client: Any,
        name: str,
        goal: Any,
        on_event: ActionEventCallback,
        time_setters: tuple[TimeSetter, ...],
    ) -> None:
        def feedback_callback(message: Any) -> None:
            on_event(ActionEvent(name, ActionEventKind.FEEDBACK, payload=message.feedback))

        self._apply_time_setters(time_setters)
        send_future = client.send_goal_async(goal, feedback_callback=feedback_callback)

        def on_goal_response(done_future: Any) -> None:
            try:
                handle = done_future.result()
            except Exception as error:
                self._entities.inflight_actions.discard(name)
                on_event(ActionEvent(name, ActionEventKind.ERROR, payload=str(error)))
                return
            if not handle.accepted:
                self._entities.inflight_actions.discard(name)
                on_event(ActionEvent(name, ActionEventKind.REJECTED))
                return
            self._entities.active_goals[name] = _ActiveGoal(handle, on_event, client)
            on_event(ActionEvent(name, ActionEventKind.ACCEPTED))
            result_future = handle.get_result_async()

            def on_result(result_done: Any) -> None:
                self._entities.active_goals.pop(name, None)
                self._entities.inflight_actions.discard(name)
                try:
                    wrapped = result_done.result()
                except Exception as error:
                    on_event(ActionEvent(name, ActionEventKind.ERROR, payload=str(error)))
                    return
                on_event(
                    ActionEvent(
                        name,
                        ActionEventKind.RESULT,
                        payload=wrapped.result,
                        status=wrapped.status,
                    )
                )

            result_future.add_done_callback(on_result)

        send_future.add_done_callback(on_goal_response)

    # ---------------------------------------------------------------- topics

    def publish_once(
        self, name: str, type_name: str, message: Any, time_setters: tuple[TimeSetter, ...] = ()
    ) -> Future:
        def command() -> None:
            publisher = self._get_publisher(name, type_name)
            self._apply_time_setters(time_setters)
            publisher.publish(message)

        return self.submit(command)

    def start_periodic_publish(
        self,
        name: str,
        type_name: str,
        message: Any,
        rate_hz: float,
        time_setters: tuple[TimeSetter, ...] = (),
    ) -> Future:
        """Publish ``message`` at ``rate_hz`` until stopped; replaces any loop on ``name``."""

        def command() -> None:
            self._stop_periodic(name)
            publisher = self._get_publisher(name, type_name)

            def tick() -> None:
                self._apply_time_setters(time_setters)
                publisher.publish(message)

            timer = self._node.create_timer(1.0 / rate_hz, tick)
            self._entities.periodic[name] = _PeriodicPublish(timer, (name, type_name))

        return self.submit(command)

    def stop_periodic_publish(self, name: str) -> Future:
        return self.submit(functools.partial(self._stop_periodic, name))

    def periodic_topics(self) -> tuple[str, ...]:
        return tuple(self._entities.periodic)  # Snapshot read; safe from any thread.

    def subscribe(self, name: str, type_name: str, buffer: EchoBuffer) -> Future:
        def command() -> None:
            if name in self._entities.subscriptions:
                return
            message_class = import_type('msg', type_name)
            qos = adapted_qos(self._node.get_publishers_info_by_topic(name))
            subscription = self._node.create_subscription(message_class, name, buffer.push, qos)
            self._entities.subscriptions[name] = subscription

        return self.submit(command)

    def unsubscribe(self, name: str) -> Future:
        def command() -> None:
            subscription = self._entities.subscriptions.pop(name, None)
            if subscription is not None:
                self._node.destroy_subscription(subscription)

        return self.submit(command)

    def topic_endpoint_counts(self, name: str) -> Future:
        """(publisher_count, subscriber_count) for ``name``, read from the graph."""

        def command() -> tuple[int, int]:
            return (
                len(self._node.get_publishers_info_by_topic(name)),
                len(self._node.get_subscriptions_info_by_topic(name)),
            )

        return self.submit(command)

    # ---------------------------------------------------------------- parameters

    def list_node_parameters(self, node_name: str, on_done: Callable) -> None:
        """Fetch all parameter names+values for ``node_name``; result via ``on_done(params, err)``."""

        def command() -> None:
            try:
                self._start_list_node_params(node_name, on_done)
            except Exception as error:
                on_done(None, str(error))

        self.submit(command)

    def _start_list_node_params(self, node_name: str, on_done: Callable) -> None:
        from rcl_interfaces.srv import ListParameters  # noqa: PLC0415
        list_srv = f'{node_name}/list_parameters'
        client = self._get_client(list_srv, 'rcl_interfaces/srv/ListParameters')
        request = ListParameters.Request()
        request.depth = ListParameters.Request.DEPTH_RECURSIVE

        def handle(done_future: Any) -> None:
            try:
                names = list(done_future.result().result.names)
                self._start_get_node_params(node_name, names, on_done)
            except Exception as error:
                on_done(None, str(error))

        self._dispatch_or_wait(
            client,
            client.service_is_ready,
            lambda: self._call_then(client, request, handle),
            lambda e: on_done(None, str(e)),
            list_srv,
        )

    def _start_get_node_params(self, node_name: str, names: list, on_done: Callable) -> None:
        if not names:
            on_done([], None)
            return
        get_srv = f'{node_name}/get_parameters'
        client = self._get_client(get_srv, 'rcl_interfaces/srv/GetParameters')

        from rcl_interfaces.srv import GetParameters  # noqa: PLC0415
        request = GetParameters.Request()
        request.names = names

        def handle(done_future: Any) -> None:
            try:
                on_done(_extract_parameters(names, done_future.result().values), None)
            except Exception as error:
                on_done(None, str(error))

        self._dispatch_or_wait(
            client,
            client.service_is_ready,
            lambda: self._call_then(client, request, handle),
            lambda e: on_done(None, str(e)),
            get_srv,
        )

    def set_node_parameter(self, node_name: str, name: str, value_yaml: str, on_done: Callable) -> None:
        """Set a single parameter on ``node_name``; result via ``on_done(error_str_or_none)``."""

        def command() -> None:
            try:
                import yaml  # noqa: PLC0415
                from rcl_interfaces.msg import Parameter  # noqa: PLC0415
                from rcl_interfaces.srv import SetParameters  # noqa: PLC0415
                value = _python_to_parameter_value(yaml.safe_load(value_yaml))
                set_srv = f'{node_name}/set_parameters'
                client = self._get_client(set_srv, 'rcl_interfaces/srv/SetParameters')
                request = SetParameters.Request(parameters=[Parameter(name=name, value=value)])

                def handle(done_future: Any) -> None:
                    try:
                        results = done_future.result().results
                        if results and not results[0].successful:
                            on_done(results[0].reason or 'rejected by node')
                        else:
                            on_done(None)
                    except Exception as error:
                        on_done(str(error))

                self._dispatch_or_wait(
                    client,
                    client.service_is_ready,
                    lambda: self._call_then(client, request, handle),
                    lambda e: on_done(str(e)),
                    set_srv,
                )
            except Exception as error:
                on_done(str(error))

        self.submit(command)

    def get_node_info(self, node_name: str, on_done: Callable) -> None:
        """Introspect ``node_name``'s endpoints; result via ``on_done(info, error)``."""

        def command() -> None:
            try:
                on_done(build_node_info(self._node, node_name), None)
            except Exception as error:
                on_done(None, str(error))

        self.submit(command)

    # ---------------------------------------------------------------- ROS thread internals

    def _ros_main(self) -> None:
        try:
            self._context = rclpy.Context()
            rclpy.init(context=self._context, signal_handler_options=SignalHandlerOptions.NO)
            self._node = rclpy.create_node(self._node_name, context=self._context)
            self._guard = self._node.create_guard_condition(self._drain_commands)
            self._node.create_timer(GRAPH_POLL_PERIOD_S, self._poll_graph)
            self._node.create_timer(HOUSEKEEPING_PERIOD_S, self._tick_pending)
            self._executor = SingleThreadedExecutor(context=self._context)
            self._executor.add_node(self._node)
        except BaseException as error:  # noqa: BLE001 - reported to start() via _startup_error
            self._startup_error = error
            self._ready.set()
            self._cleanup_partial_init()
            return
        self._ready.set()
        try:
            self._poll_graph()
            while self._running:
                self._executor.spin_once(timeout_sec=0.1)
        except ExternalShutdownException:
            pass  # Context shut down from outside; fall through to teardown.
        finally:
            # Whatever killed the loop, leave the bridge unusable-but-consistent:
            # submit() must raise instead of stranding futures, and entities must die.
            with self._submit_lock:
                self._running = False
            self._teardown()

    def _cleanup_partial_init(self) -> None:
        if self._node is not None:
            with contextlib.suppress(Exception):
                self._node.destroy_node()
        if self._context is not None:
            with contextlib.suppress(Exception):
                rclpy.shutdown(context=self._context)

    def _drain_commands(self) -> None:
        while True:
            try:
                command, future = self._commands.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(command())
            except BaseException as error:  # noqa: BLE001 - surfaced to the caller
                future.set_exception(error)

    def _guarded(self, outer: Future, fn: Callable[..., None], *args: Any) -> Callable[[], None]:
        """Wrap an async-starting command so its synchronous part fails into ``outer``."""

        def command() -> None:
            try:
                fn(*args, outer)
            except Exception as error:
                if not outer.done():
                    outer.set_exception(error)

        return command

    def _dispatch_or_wait(
        self,
        entity: Any,
        is_ready: Callable[[], bool],
        dispatch: Callable[[], None],
        fail: Callable[[Exception], None],
        label: str,
    ) -> None:
        """Dispatch now if the server is ready, else queue until it is (or the deadline). ROS thread."""
        if is_ready():
            dispatch()
        else:
            self._entities.pending_ready.append(
                _PendingReady(
                    entity=entity,
                    is_ready=is_ready,
                    dispatch=dispatch,
                    fail=fail,
                    deadline=time.monotonic() + READY_TIMEOUT_S,
                    label=label,
                )
            )

    def _call_then(self, client: Any, request: Any, handle: Callable[[Any], None]) -> None:
        """Call ``client`` async; when the response lands, run ``handle(future)`` on the ROS thread.

        Tracks ``client`` in ``awaiting_response`` for the call's lifetime so the LRU cache in
        ``_get_or_create`` cannot pick it as an eviction victim and ``destroy_client`` it mid-flight.
        """
        rclpy_future = client.call_async(request)
        record = _AwaitingResponse(
            client=client,
            rclpy_future=rclpy_future,
            deadline=time.monotonic() + RESPONSE_TIMEOUT_S,
            label=getattr(client, 'srv_name', 'parameter call'),
        )
        self._entities.awaiting_response.append(record)

        def on_done(done: Any) -> None:
            with contextlib.suppress(ValueError):
                self._entities.awaiting_response.remove(record)
            self.submit(lambda: handle(done))

        rclpy_future.add_done_callback(on_done)

    def _poll_graph(self) -> None:
        previous = self._latest_graph
        snapshot = build_snapshot(self._node, previous.version + 1)
        unchanged = (
            snapshot.actions == previous.actions
            and snapshot.services == previous.services
            and snapshot.topics == previous.topics
            and snapshot.nodes == previous.nodes
        )
        if unchanged:
            return
        self._latest_graph = snapshot
        listener = self._graph_listener
        if listener is not None:
            with contextlib.suppress(Exception):
                listener(snapshot)

    def _tick_pending(self) -> None:
        now = time.monotonic()
        still_pending = []
        for pending in self._entities.pending_ready:
            try:
                if pending.is_ready():
                    pending.dispatch()
                elif now >= pending.deadline:
                    pending.fail(TimeoutError(f'{pending.label} not available (no server found)'))
                else:
                    still_pending.append(pending)
            except Exception as error:  # noqa: BLE001 - one bad entry must not kill housekeeping
                with contextlib.suppress(Exception):
                    pending.fail(error)
        self._entities.pending_ready = still_pending

        # Watchdog: an action server dying mid-goal would otherwise leave the goal
        # EXECUTING forever (its result future never completes) and block new sends.
        for name, active in list(self._entities.active_goals.items()):
            if active.client.server_is_ready():
                active.server_lost_since = None
            elif active.server_lost_since is None:
                active.server_lost_since = now
            elif now - active.server_lost_since >= READY_TIMEOUT_S:
                self._entities.active_goals.pop(name, None)
                self._entities.inflight_actions.discard(name)
                with contextlib.suppress(Exception):
                    active.on_event(
                        ActionEvent(
                            name,
                            ActionEventKind.ERROR,
                            payload='action server vanished while the goal was executing',
                        )
                    )

        still_awaiting = []
        for record in self._entities.awaiting_response:
            if now >= record.deadline:
                with contextlib.suppress(Exception):
                    record.client.remove_pending_request(record.rclpy_future)
                if record.outer is not None and not record.outer.done():
                    record.outer.set_exception(
                        TimeoutError(
                            f'no response from {record.label} after {RESPONSE_TIMEOUT_S:.0f} s'
                        )
                    )
            else:
                still_awaiting.append(record)
        self._entities.awaiting_response = still_awaiting

    def _apply_time_setters(self, time_setters: tuple[TimeSetter, ...]) -> None:
        if not time_setters:
            return
        now = self._node.get_clock().now().to_msg()
        for setter in time_setters:
            setter(now)

    # ---------------------------------------------------------------- entity caches

    def _get_client(self, name: str, type_name: str) -> Any:
        return self._get_or_create(
            self._entities.clients,
            (name, type_name),
            lambda: self._node.create_client(import_type('srv', type_name), name),
            self._client_in_use,
            self._node.destroy_client,
        )

    def _get_action_client(self, name: str, type_name: str) -> Any:
        return self._get_or_create(
            self._entities.action_clients,
            (name, type_name),
            lambda: ActionClient(self._node, import_type('action', type_name), name),
            self._action_client_in_use,
            lambda client: client.destroy(),
        )

    def _get_publisher(self, name: str, type_name: str) -> Any:
        return self._get_or_create(
            self._entities.publishers,
            (name, type_name),
            lambda: self._node.create_publisher(
                import_type('msg', type_name), name, QoSProfile(depth=DEFAULT_QOS_DEPTH)
            ),
            self._publisher_in_use,
            self._node.destroy_publisher,
        )

    def _get_or_create(
        self,
        cache: OrderedDict,
        key: tuple[str, str],
        factory: Callable[[], Any],
        in_use: Callable[[tuple[str, str], Any], bool],
        destroy: Callable[[Any], None],
    ) -> Any:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        entity = factory()
        cache[key] = entity
        while len(cache) > CLIENT_CACHE_SIZE:
            victim_key = next(
                (candidate for candidate in cache if not in_use(candidate, cache[candidate])),
                None,
            )
            if victim_key is None:
                break  # Everything is busy; tolerate the overflow rather than break a call.
            with contextlib.suppress(Exception):
                destroy(cache.pop(victim_key))
        return entity

    def _client_in_use(self, key: tuple[str, str], client: Any) -> bool:
        return any(record.client is client for record in self._entities.awaiting_response) or any(
            pending.entity is client for pending in self._entities.pending_ready
        )

    def _action_client_in_use(self, key: tuple[str, str], client: Any) -> bool:
        # inflight_actions also covers the window between send_goal_async and goal response,
        # where the client is in neither pending_ready nor active_goals.
        return (
            any(active.client is client for active in self._entities.active_goals.values())
            or any(pending.entity is client for pending in self._entities.pending_ready)
            or key[0] in self._entities.inflight_actions
        )

    def _publisher_in_use(self, key: tuple[str, str], publisher: Any) -> bool:
        return any(periodic.publisher_key == key for periodic in self._entities.periodic.values())

    def _stop_periodic(self, name: str) -> None:
        periodic = self._entities.periodic.pop(name, None)
        if periodic is not None:
            self._node.destroy_timer(periodic.timer)

    # ---------------------------------------------------------------- teardown

    def _cancel_goals(self) -> None:
        """Cancel the goals still running, as ``ros2 action send_goal`` does on ctrl+c: nothing keeps
        acting on the robot after the app quits. A goal whose acceptance is still on its way is
        canceled once it arrives. Spins for at most SHUTDOWN_CANCEL_TIMEOUT_S, until every server
        answered (queued commands and parked requests are already gone, so only replies run)."""
        entities = self._entities
        canceling: dict[str, Any] = {}
        deadline = time.monotonic() + SHUTDOWN_CANCEL_TIMEOUT_S
        while self._context.ok() and time.monotonic() < deadline:
            for name, active in entities.active_goals.items():
                if name not in canceling:
                    canceling[name] = active.handle.cancel_goal_async()
            if entities.inflight_actions <= canceling.keys() and all(f.done() for f in canceling.values()):
                return
            self._executor.spin_once(timeout_sec=0.05)

    def _teardown(self) -> None:
        while True:
            try:
                _, future = self._commands.get_nowait()
            except queue.Empty:
                break
            future.cancel()
        entities = self._entities
        shutdown_error = RuntimeError('ROS bridge shut down')
        for pending in entities.pending_ready:
            with contextlib.suppress(Exception):
                pending.fail(shutdown_error)
        for record in entities.awaiting_response:
            if not record.outer.done():
                record.outer.set_exception(shutdown_error)
        entities.pending_ready = []
        entities.awaiting_response = []
        with contextlib.suppress(Exception):
            self._cancel_goals()
        with contextlib.suppress(Exception):
            for periodic in list(entities.periodic.values()):
                self._node.destroy_timer(periodic.timer)
            for subscription in entities.subscriptions.values():
                self._node.destroy_subscription(subscription)
            for publisher in entities.publishers.values():
                self._node.destroy_publisher(publisher)
            for client in entities.clients.values():
                self._node.destroy_client(client)
            for action_client in entities.action_clients.values():
                action_client.destroy()
            self._node.destroy_guard_condition(self._guard)
        with contextlib.suppress(Exception):
            self._node.destroy_node()
        with contextlib.suppress(Exception):
            rclpy.shutdown(context=self._context)
