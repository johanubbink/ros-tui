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
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable

import rclpy
from rcl_interfaces.msg import Parameter
from rcl_interfaces.srv import GetParameters, ListParameters, SetParameters
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions

from ros_tui.constants import (
    CLIENT_CACHE_SIZE,
    DEFAULT_QOS_DEPTH,
    GRAPH_POLL_PERIOD_S,
    HOUSEKEEPING_PERIOD_S,
    SHUTDOWN_CANCEL_TIMEOUT_S,
)
from ros_tui.ros.contract import (
    ActionEventCallback,
    GraphListener,
    NodeInfoDone,
    ParametersDone,
    SetParameterDone,
)
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.entity_cache import EntityCache
from ros_tui.ros.events import ActionEvent, ActionEventKind
from ros_tui.ros.graph import EMPTY_GRAPH, GraphSnapshot, build_node_info, build_snapshot
from ros_tui.ros.inflight import Inflight
from ros_tui.ros.message_yaml import TimeSetter, import_type
from ros_tui.ros.parameters import parameter_value, read_parameters


def _once(on_done: Callable[..., None]) -> Callable[..., None]:
    """``on_done`` run at most once: a later call is ignored. A request whose on_done raised then
    fails with that error, and its caller must not hear about the same request twice."""
    called = False

    def call(*answer: Any) -> None:
        nonlocal called
        if not called:
            called = True
            on_done(*answer)

    return call


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
class _PeriodicPublish:
    timer: Any
    publisher: Any


@dataclass
class _Entities:
    """All ROS-thread-only mutable state, grouped so the ownership rule is visible."""

    inflight: Inflight
    clients: EntityCache
    action_clients: EntityCache
    publishers: EntityCache
    subscriptions: dict = field(default_factory=dict)
    periodic: dict = field(default_factory=dict)


class RosBridge:
    """The bridge contract (ros/contract.py) over one rclpy node spun on a dedicated thread."""

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
        inflight = Inflight()
        self._entities = _Entities(
            inflight=inflight,
            clients=EntityCache(
                CLIENT_CACHE_SIZE, inflight.busy, lambda client: self._node.destroy_client(client)
            ),
            action_clients=EntityCache(
                CLIENT_CACHE_SIZE, inflight.busy, lambda client: client.destroy()
            ),
            publishers=EntityCache(
                CLIENT_CACHE_SIZE,
                self._publisher_in_use,
                lambda publisher: self._node.destroy_publisher(publisher),
            ),
        )

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

    def time_of_day(self) -> float:
        """The local time of day in seconds since midnight, for the activity lines' "09:41:03"."""
        now = time.time()
        local = time.localtime(now)
        return local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec + now % 1

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
        self._entities.inflight.wait_for_server(
            client, client.service_is_ready, dispatch, outer.set_exception, name
        )

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

        def on_response(done_future: Any) -> None:
            if outer.done():
                return
            error = done_future.exception()
            if error is not None:
                outer.set_exception(error)
            else:
                outer.set_result(done_future.result())

        def on_fail(error: Exception) -> None:
            if not outer.done():
                outer.set_exception(error)

        self._entities.inflight.track_response(client, rclpy_future, name, on_response, on_fail)

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
            active = self._entities.inflight.goals().get(name)
            if active is None or active.handle is None:
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
        inflight = self._entities.inflight
        if name in inflight.goals():
            on_event(ActionEvent(name, ActionEventKind.ERROR, payload='goal already in flight'))
            return
        client = self._get_action_client(name, type_name)
        inflight.begin_goal(name, client, on_event)
        dispatch = functools.partial(
            self._dispatch_goal, client, name, goal, on_event, time_setters
        )

        def fail(error: Exception) -> None:
            inflight.end_goal(name)
            on_event(ActionEvent(name, ActionEventKind.ERROR, payload=str(error)))

        inflight.wait_for_server(client, client.server_is_ready, dispatch, fail, name)

    def _dispatch_goal(
        self,
        client: Any,
        name: str,
        goal: Any,
        on_event: ActionEventCallback,
        time_setters: tuple[TimeSetter, ...],
    ) -> None:
        inflight = self._entities.inflight

        def feedback_callback(message: Any) -> None:
            on_event(ActionEvent(name, ActionEventKind.FEEDBACK, payload=message.feedback))

        self._apply_time_setters(time_setters)
        send_future = client.send_goal_async(goal, feedback_callback=feedback_callback)

        def on_goal_response(done_future: Any) -> None:
            try:
                handle = done_future.result()
            except Exception as error:
                inflight.end_goal(name)
                on_event(ActionEvent(name, ActionEventKind.ERROR, payload=str(error)))
                return
            if not handle.accepted:
                inflight.end_goal(name)
                on_event(ActionEvent(name, ActionEventKind.REJECTED))
                return
            inflight.goal_accepted(name, handle)
            on_event(ActionEvent(name, ActionEventKind.ACCEPTED))
            result_future = handle.get_result_async()

            def on_result(result_done: Any) -> None:
                inflight.end_goal(name)
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
            self._entities.periodic[name] = _PeriodicPublish(timer, publisher)

        return self.submit(command)

    def stop_periodic_publish(self, name: str) -> Future:
        return self.submit(functools.partial(self._stop_periodic, name))

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

    # ---------------------------------------------------------------- parameters

    def list_node_parameters(self, node_name: str, on_done: ParametersDone) -> None:
        on_done = _once(on_done)

        def fail(error: Exception) -> None:
            on_done(None, str(error))

        def listed(response: Any) -> None:
            names = list(response.result.names)
            if not names:
                on_done([], None)
                return
            self._parameter_request(
                f'{node_name}/get_parameters',
                GetParameters,
                lambda: GetParameters.Request(names=names),
                lambda got: on_done(read_parameters(names, got.values), None),
                fail,
            )

        self.submit(lambda: self._parameter_request(
            f'{node_name}/list_parameters',
            ListParameters,
            lambda: ListParameters.Request(depth=ListParameters.Request.DEPTH_RECURSIVE),
            listed,
            fail,
        ))

    def set_node_parameter(
        self, node_name: str, name: str, value: Any, type_label: str, on_done: SetParameterDone
    ) -> None:
        on_done = _once(on_done)

        def answered(response: Any) -> None:
            results = response.results
            if results and not results[0].successful:
                on_done(results[0].reason or 'rejected by node')
            else:
                on_done(None)

        self.submit(lambda: self._parameter_request(
            f'{node_name}/set_parameters',
            SetParameters,
            lambda: SetParameters.Request(
                parameters=[Parameter(name=name, value=parameter_value(value, type_label))]
            ),
            answered,
            lambda error: on_done(str(error)),
        ))

    def get_node_info(self, node_name: str, on_done: NodeInfoDone) -> None:
        def command() -> None:
            try:
                info = build_node_info(self._node, node_name)
            except Exception as error:
                on_done(None, str(error))
                return
            on_done(info, None)

        self.submit(command)

    # ---------------------------------------------------------------- ROS thread internals

    def _ros_main(self) -> None:
        try:
            self._context = rclpy.Context()
            rclpy.init(context=self._context, signal_handler_options=SignalHandlerOptions.NO)
            self._node = rclpy.create_node(self._node_name, context=self._context)
            self._guard = self._node.create_guard_condition(self._drain_commands)
            self._node.create_timer(GRAPH_POLL_PERIOD_S, self._poll_graph)
            self._node.create_timer(HOUSEKEEPING_PERIOD_S, self._entities.inflight.housekeep)
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

    def _parameter_request(
        self,
        service_name: str,
        service_type: Any,
        make_request: Callable[[], Any],
        on_response: Callable[[Any], None],
        fail: Callable[[Exception], None],
    ) -> None:
        """Call the rcl_interfaces parameter service ``service_name`` (ROS thread).

        ``on_response(response)`` runs on the ROS thread when it answers, straight from the reply,
        never through the command queue, so a reply that lands while shutdown is under way is
        handled like any other. Otherwise ``fail(error)`` runs, once: building the request or
        sending it raised, no server within READY_TIMEOUT_S, no response within
        RESPONSE_TIMEOUT_S, shutdown, or ``on_response`` raised. As ``on_response`` may have
        answered the caller before it raised, the caller's on_done is wrapped in ``_once``. An
        exception from ``fail`` on the reply is dropped, so it can't stop the spin loop."""

        def reply(done: Any) -> None:
            try:
                on_response(done.result())
            except Exception as error:
                with contextlib.suppress(Exception):
                    fail(error)

        def dispatch() -> None:
            future = client.call_async(make_request())
            self._entities.inflight.track_response(client, future, service_name, reply, fail)

        try:
            client = self._get_client(service_name, f'rcl_interfaces/srv/{service_type.__name__}')
            self._entities.inflight.wait_for_server(
                client, client.service_is_ready, dispatch, fail, service_name
            )
        except Exception as error:
            fail(error)

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

    def _apply_time_setters(self, time_setters: tuple[TimeSetter, ...]) -> None:
        if not time_setters:
            return
        now = self._node.get_clock().now().to_msg()
        for setter in time_setters:
            setter(now)

    # ---------------------------------------------------------------- entity caches

    def _get_client(self, name: str, type_name: str) -> Any:
        return self._entities.clients.get(
            (name, type_name),
            lambda: self._node.create_client(import_type('srv', type_name), name),
        )

    def _get_action_client(self, name: str, type_name: str) -> Any:
        return self._entities.action_clients.get(
            (name, type_name),
            lambda: ActionClient(self._node, import_type('action', type_name), name),
        )

    def _get_publisher(self, name: str, type_name: str) -> Any:
        return self._entities.publishers.get(
            (name, type_name),
            lambda: self._node.create_publisher(
                import_type('msg', type_name), name, QoSProfile(depth=DEFAULT_QOS_DEPTH)
            ),
        )

    def _publisher_in_use(self, publisher: Any) -> bool:
        return any(periodic.publisher is publisher for periodic in self._entities.periodic.values())

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
        canceling: dict[str, Any] = {}
        deadline = time.monotonic() + SHUTDOWN_CANCEL_TIMEOUT_S
        while self._context.ok() and time.monotonic() < deadline:
            goals = self._entities.inflight.goals()
            for name, goal in goals.items():
                if goal.handle is not None and name not in canceling:
                    canceling[name] = goal.handle.cancel_goal_async()
            if goals.keys() <= canceling.keys() and all(f.done() for f in canceling.values()):
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
        entities.inflight.fail_all(RuntimeError('ROS bridge shut down'))
        with contextlib.suppress(Exception):
            self._cancel_goals()
        with contextlib.suppress(Exception):
            for periodic in list(entities.periodic.values()):
                self._node.destroy_timer(periodic.timer)
            for subscription in entities.subscriptions.values():
                self._node.destroy_subscription(subscription)
            entities.publishers.destroy_all()
            entities.clients.destroy_all()
            entities.action_clients.destroy_all()
            self._node.destroy_guard_condition(self._guard)
        with contextlib.suppress(Exception):
            self._node.destroy_node()
        with contextlib.suppress(Exception):
            rclpy.shutdown(context=self._context)
