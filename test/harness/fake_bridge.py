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

"""A ``RosBridge`` stand-in without rclpy, for UI tests and the screenshot harness.

``FakeBridge`` implements the bridge contract the UI uses and records every call. It runs in one
of two modes:

- **canned** (the default, ``FakeBridge()``): nothing happens on its own. Service futures stay
  pending and action events are never emitted; the test resolves them by hand
  (``bridge.service_future.set_result(...)``, ``bridge.on_event(...)``).
- **live** (``FakeBridge.demo()``, or ``live=True``): a small simulated world driven by a
  ``ManualClock``. Services answer after ``SERVICE_DELAY_S`` (AddTwoInts returns the real sum),
  actions are accepted, stream feedback and then succeed (or cancel), and echo subscriptions get
  messages pushed into their ``EchoBuffer`` at each topic's rate. Time only moves when the test
  calls ``bridge.clock.advance(seconds)``, so screenshots are deterministic.

Everything runs on the caller's thread (the UI thread under Pilot). That is fine for the UI: its
bridge callbacks only call ``post_message``, which is safe from any thread.
"""

import heapq
import itertools
import math
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

from action_msgs.msg import GoalStatus
from builtin_interfaces.msg import Time
from diagnostic_msgs.msg import DiagnosticStatus
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from geometry_msgs.msg import PoseWithCovarianceStamped
from ros_tui.ros.events import ActionEvent, ActionEventKind
from ros_tui.ros.graph import GraphSnapshot, InterfaceEntry, NodeInfo
from ros_tui.ros.message_yaml import import_type
from std_msgs.msg import Int32, String

SERVICE_DELAY_S = 0.05  # Live services answer this long after the call.
ACTION_FEEDBACK_PERIOD_S = 0.3  # Live actions send one feedback per period (as the demo servers do).
STAMP_EPOCH_S = 1728036000  # Stamps of simulated messages count from here (as the design does).

# ---------------------------------------------------------------- the canned world (old tests)

FIBONACCI_ENTRY = InterfaceEntry('/fibonacci', ('example_interfaces/action/Fibonacci',))
ADD_TWO_INTS_ENTRY = InterfaceEntry('/add_two_ints', ('example_interfaces/srv/AddTwoInts',))
CHATTER_ENTRY = InterfaceEntry('/chatter', ('std_msgs/msg/String',))
POSE_ENTRY = InterfaceEntry('/pose', ('geometry_msgs/msg/PoseStamped',))
DIAG_ENTRY = InterfaceEntry('/diag', ('diagnostic_msgs/msg/DiagnosticStatus',))
TALKER_NODE = InterfaceEntry('/talker', ('/',))  # nodes store their namespace in types[0].

SNAPSHOT = GraphSnapshot(
    version=1,
    actions=(FIBONACCI_ENTRY,),
    services=(ADD_TWO_INTS_ENTRY, InterfaceEntry('/set_bool', ('std_srvs/srv/SetBool',))),
    topics=(CHATTER_ENTRY, POSE_ENTRY, DIAG_ENTRY),
    nodes=(TALKER_NODE,),
)

# Canned introspection for /talker; entries match SNAPSHOT so jumps can highlight the target.
NODE_INFO = NodeInfo(
    node_name='/talker',
    publishers=(CHATTER_ENTRY,),
    subscribers=(POSE_ENTRY,),
    service_servers=(ADD_TWO_INTS_ENTRY,),
    service_clients=(),
    action_servers=(FIBONACCI_ENTRY,),
    action_clients=(),
)
NODE_PARAMS = [('use_sim_time', 'bool', False), ('rate', 'double', 10.0)]

# ---------------------------------------------------------------- the demo world

DEMO_TOPICS = {
    'chatter': InterfaceEntry('/chatter', ('std_msgs/msg/String',)),
    'counter': InterfaceEntry('/counter', ('std_msgs/msg/Int32',)),
    'diagnostic_status': InterfaceEntry('/diagnostic_status', ('diagnostic_msgs/msg/DiagnosticStatus',)),
    'inbox': InterfaceEntry('/inbox', ('std_msgs/msg/String',)),
    'localisation_pose': InterfaceEntry(
        '/localisation_pose', ('geometry_msgs/msg/PoseWithCovarianceStamped',)
    ),
    'goal_pose': InterfaceEntry('/goal_pose', ('geometry_msgs/msg/PoseStamped',)),
}
DEMO_SERVICES = {
    'add_two_ints': InterfaceEntry('/add_two_ints', ('example_interfaces/srv/AddTwoInts',)),
    'set_pose': InterfaceEntry('/set_pose', ('turtlesim/srv/TeleportAbsolute',)),
}
DEMO_ACTIONS = {
    'fibonacci': InterfaceEntry('/fibonacci', ('example_interfaces/action/Fibonacci',)),
}
DEMO_NODES = {
    'demo_servers': InterfaceEntry('/ros_tui_demo_servers', ('/',)),
    'talker': InterfaceEntry('/talker', ('/',)),
}

# Mirrors ros_tui/demo/demo_servers.py (plus /talker) and the KINDS table of the design prototype.
DEMO_GRAPH = GraphSnapshot(
    version=1,
    actions=tuple(DEMO_ACTIONS.values()),
    services=tuple(DEMO_SERVICES.values()),
    topics=tuple(DEMO_TOPICS.values()),
    nodes=tuple(DEMO_NODES.values()),
)

DEMO_NODE_INFOS = {
    '/ros_tui_demo_servers': NodeInfo(
        node_name='/ros_tui_demo_servers',
        publishers=tuple(DEMO_TOPICS[n] for n in ('chatter', 'counter', 'diagnostic_status', 'localisation_pose')),
        subscribers=(DEMO_TOPICS['inbox'], DEMO_TOPICS['goal_pose']),
        service_servers=tuple(DEMO_SERVICES.values()),
        service_clients=(),
        action_servers=tuple(DEMO_ACTIONS.values()),
        action_clients=(),
    ),
    '/talker': NodeInfo(
        node_name='/talker',
        publishers=(DEMO_TOPICS['chatter'],),
        subscribers=(),
        service_servers=(),
        service_clients=(),
        action_servers=(),
        action_clients=(),
    ),
}
DEMO_PARAMS = [('use_sim_time', 'bool', False), ('publish_rate', 'double', 10.0), ('frame_id', 'string', 'map')]

_DIAGNOSTIC_LEVELS = (
    (DiagnosticStatus.OK, 'OK'),
    (DiagnosticStatus.WARN, 'WARN'),
    (DiagnosticStatus.ERROR, 'ERROR'),
    (DiagnosticStatus.STALE, 'STALE'),
)


def _stamp(now_s: float) -> Time:
    seconds = STAMP_EPOCH_S + now_s
    return Time(sec=int(seconds), nanosec=int(round((seconds % 1.0) * 1e9)) % 1_000_000_000)


def _chatter(index: int, now_s: float) -> String:
    return String(data=f'chatter {index}')


def _counter(index: int, now_s: float) -> Int32:
    return Int32(data=index)


def _diagnostic_status(index: int, now_s: float) -> DiagnosticStatus:
    level, label = _DIAGNOSTIC_LEVELS[(index - 1) % len(_DIAGNOSTIC_LEVELS)]
    return DiagnosticStatus(
        level=level, name='demo_check', message=f'cycling level: {label}', hardware_id='demo-0'
    )


def _localisation_pose(index: int, now_s: float) -> PoseWithCovarianceStamped:
    angle = index * 0.5  # radians, ~1 rad/s at 2 Hz (as the demo servers do).
    message = PoseWithCovarianceStamped()
    message.header.stamp = _stamp(now_s)
    message.header.frame_id = 'map'
    pose = message.pose.pose
    pose.position.x = 2.0 * math.cos(angle)
    pose.position.y = 2.0 * math.sin(angle)
    pose.orientation.z = math.sin(angle / 2.0)
    pose.orientation.w = math.cos(angle / 2.0)
    return message


@dataclass(frozen=True)
class TopicFeed:
    """What a simulated publisher sends: ``make(index, now_s)`` at ``rate_hz`` (index from 1)."""

    rate_hz: float
    make: Callable[[int, float], Any]


# Topics nobody publishes (/inbox, /goal_pose) have no feed: an echo on them stays silent.
DEMO_FEEDS = {
    '/chatter': TopicFeed(1.0, _chatter),
    '/counter': TopicFeed(50.0, _counter),
    '/diagnostic_status': TopicFeed(1.0, _diagnostic_status),
    '/localisation_pose': TopicFeed(2.0, _localisation_pose),
}


def _add_two_ints(request):
    return AddTwoInts.Response(sum=request.a + request.b)


# name -> request -> response. Services without an entry answer with a default Response.
DEMO_RESPONDERS = {'/add_two_ints': _add_two_ints}


@dataclass(frozen=True)
class ActionScript:
    """How a simulated action server runs a goal: ``steps(goal)`` feedbacks, then the result.

    ``feedback(goal, step)`` builds the feedback for step 1..N and ``result(goal, steps_done)`` the
    result (``steps_done`` is less than N when the goal was canceled).
    """

    steps: Callable[[Any], int]
    feedback: Callable[[Any, int], Any]
    result: Callable[[Any, int], Any]


def _fibonacci_sequence(steps_done: int) -> list[int]:
    sequence = [0, 1]
    for _ in range(steps_done):
        sequence.append(sequence[-1] + sequence[-2])
    return sequence


# Like the demo server: order N gives N-1 feedbacks, each one number longer.
DEMO_ACTION_SCRIPTS = {
    '/fibonacci': ActionScript(
        steps=lambda goal: max(1, goal.order - 1),
        feedback=lambda goal, step: Fibonacci.Feedback(sequence=_fibonacci_sequence(step)),
        result=lambda goal, done: Fibonacci.Result(sequence=_fibonacci_sequence(done)),
    ),
}


def completed_future(result=None):
    future = Future()
    future.set_result(result)
    return future


class _Timer:
    def __init__(self):
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualClock:
    """Simulated time: callbacks run only inside ``advance()``, in due-time order."""

    def __init__(self):
        self.now = 0.0
        self._queue: list[tuple[float, int, _Timer, Callable[[], Any], float | None]] = []
        self._sequence = itertools.count()

    def call_later(self, delay_s: float, callback: Callable[[], Any]) -> _Timer:
        return self._schedule(self.now + delay_s, callback, None)

    def call_every(self, period_s: float, callback: Callable[[], Any]) -> _Timer:
        """Run ``callback`` every ``period_s``, first one period from now; ``cancel()`` stops it."""
        return self._schedule(self.now + period_s, callback, period_s)

    def advance(self, seconds: float) -> None:
        """Move time forward by ``seconds``, running every callback that falls due on the way."""
        target = self.now + seconds
        # A small tolerance so a 1 Hz timer fires at exactly t=1.0 after ten 0.1 s steps.
        while self._queue and self._queue[0][0] <= target + 1e-9:
            due, _, timer, callback, period = heapq.heappop(self._queue)
            if timer.cancelled:
                continue
            self.now = max(self.now, due)
            if period is not None:
                heapq.heappush(self._queue, (due + period, next(self._sequence), timer, callback, period))
            callback()
        self.now = target

    def _schedule(self, due: float, callback, period) -> _Timer:
        timer = _Timer()
        heapq.heappush(self._queue, (due, next(self._sequence), timer, callback, period))
        return timer


class FakeBridge:
    """The bridge contract the UI uses, recorded; canned by default, simulated when ``live``."""

    def __init__(
        self,
        snapshot: GraphSnapshot = SNAPSHOT,
        *,
        live: bool = False,
        clock: ManualClock | None = None,
        node_infos: dict[str, NodeInfo] | None = None,
        params: list[tuple[str, str, Any]] | None = None,
        feeds: dict[str, TopicFeed] | None = None,
        responders: dict[str, Callable[[Any], Any]] | None = None,
        action_scripts: dict[str, ActionScript] | None = None,
    ):
        self.latest_graph = snapshot
        self.live = live
        self.clock = clock or ManualClock()
        self.node_infos = {'/talker': NODE_INFO} if node_infos is None else node_infos
        self.params = NODE_PARAMS if params is None else params
        self.feeds = feeds or {}
        self.responders = responders or {}
        self.action_scripts = action_scripts or {}
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
        self.topic_counts_requests = []
        self.node_info_requests = []
        self.param_list_requests = []
        self.set_param_calls = []
        self._feed_timers: dict[str, _Timer] = {}
        self._goals: dict[str, '_LiveGoal'] = {}

    @classmethod
    def demo(cls, clock: ManualClock | None = None) -> 'FakeBridge':
        """A live bridge over ``DEMO_GRAPH``: the same world as the demo servers and the design."""
        return cls(
            DEMO_GRAPH,
            live=True,
            clock=clock,
            node_infos=DEMO_NODE_INFOS,
            params=DEMO_PARAMS,
            feeds=DEMO_FEEDS,
            responders=DEMO_RESPONDERS,
            action_scripts=DEMO_ACTION_SCRIPTS,
        )

    # ---------------------------------------------------------------- clock

    def now(self) -> float:
        """The UI's clock: simulated time, so toasts expire on ``advance()``, not in real time."""
        return self.clock.now

    # ---------------------------------------------------------------- graph + nodes

    def set_graph_listener(self, listener):
        self.listener = listener

    def get_node_info(self, node_name, on_done):
        self.node_info_requests.append(node_name)
        info = self.node_infos.get(node_name)
        if info is None:
            info = NodeInfo(node_name, (), (), (), (), (), ())
        on_done(info, None)

    def list_node_parameters(self, node_name, on_done):
        self.param_list_requests.append(node_name)
        on_done(list(self.params), None)

    def set_node_parameter(self, node_name, name, value_yaml, on_done):
        self.set_param_calls.append((node_name, name, value_yaml))
        on_done(None)

    # ---------------------------------------------------------------- services

    def call_service(self, name, type_name, request, time_setters=()):
        self.service_calls.append((name, type_name, request))
        future = Future()
        self.service_future = future
        if self.live:
            self.clock.call_later(SERVICE_DELAY_S, lambda: self._answer(future, name, type_name, request))
        return future

    def _answer(self, future, name, type_name, request):
        if future.done():
            return
        responder = self.responders.get(name)
        try:
            response = responder(request) if responder else import_type('srv', type_name).Response()
        except Exception as error:  # noqa: BLE001 - surfaced to the UI like a failed call
            future.set_exception(error)
            return
        future.set_result(response)

    # ---------------------------------------------------------------- actions

    def send_goal(self, name, type_name, goal, on_event, time_setters=()):
        self.sent_goals.append((name, type_name, goal))
        self.on_event = on_event
        if self.live:
            if name in self._goals:
                on_event(ActionEvent(name, ActionEventKind.ERROR, payload='goal already in flight'))
                return
            self._goals[name] = _LiveGoal(self, name, type_name, goal, on_event)

    def cancel_goal(self, name):
        self.cancelled.append(name)
        goal = self._goals.get(name) if self.live else None
        if goal is not None:
            goal.cancel()

    # ---------------------------------------------------------------- topics

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
        feed = self.feeds.get(name) if self.live else None
        if feed is not None and name not in self._feed_timers:
            counter = itertools.count(1)
            self._feed_timers[name] = self.clock.call_every(
                1.0 / feed.rate_hz, lambda: buffer.push(feed.make(next(counter), self.clock.now))
            )
        return completed_future()

    def unsubscribe(self, name):
        self.subscriptions.pop(name, None)
        timer = self._feed_timers.pop(name, None)
        if timer is not None:
            timer.cancel()
        return completed_future()

    def pending_echo(self) -> int:
        """Messages pushed into echo buffers that the UI has not drained yet."""
        return sum(buffer.pending() for buffer in self.subscriptions.values())

    def topic_endpoint_counts(self, name):
        self.topic_counts_requests.append(name)
        if self.live:
            publishers = 1 if name in self.feeds else 0
            return completed_future((publishers, 0 if publishers else 1))
        return completed_future((1, 2))

    def shutdown(self):
        for timer in self._feed_timers.values():
            timer.cancel()
        self._feed_timers.clear()


class _LiveGoal:
    """One simulated goal: accepted now, feedback every period, then SUCCEEDED (or CANCELED)."""

    def __init__(self, bridge: FakeBridge, name: str, type_name: str, goal: Any, on_event):
        self._bridge, self._name, self._goal, self._on_event = bridge, name, goal, on_event
        script = bridge.action_scripts.get(name)
        if script is None:
            action = import_type('action', type_name)
            script = ActionScript(lambda goal: 3, lambda goal, step: action.Feedback(),
                                  lambda goal, done: action.Result())
        self._script = script
        self._steps = script.steps(goal)
        self._done = 0
        on_event(ActionEvent(name, ActionEventKind.ACCEPTED))
        self._timer = bridge.clock.call_every(ACTION_FEEDBACK_PERIOD_S, self._tick)

    def _tick(self) -> None:
        if self._done >= self._steps:
            self._finish(GoalStatus.STATUS_SUCCEEDED)
            return
        self._done += 1
        feedback = self._script.feedback(self._goal, self._done)
        self._on_event(ActionEvent(self._name, ActionEventKind.FEEDBACK, payload=feedback))

    def cancel(self) -> None:
        self._on_event(ActionEvent(self._name, ActionEventKind.CANCEL_ACCEPTED))
        self._finish(GoalStatus.STATUS_CANCELED)

    def _finish(self, status: int) -> None:
        self._timer.cancel()
        self._bridge._goals.pop(self._name, None)
        result = self._script.result(self._goal, self._done)
        self._on_event(ActionEvent(self._name, ActionEventKind.RESULT, payload=result, status=status))
