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

"""The bridge contract: everything the UI may ask of ROS, and how each request answers.

`RosBridge` (ros/bridge.py) implements it over rclpy on its own thread; `FakeBridge`
(test/harness/fake_bridge.py) implements it without rclpy for the tests. test/test_contract.py
checks that both define every member with the same parameters, and that ros_tui/ui calls nothing
else on a bridge.

How answers arrive. A request returns at once and answers in one of three ways, named per member:

- **Future**: a `concurrent.futures.Future`. Its done-callbacks run on the ROS thread when the
  bridge settles it, or straight away on the caller's thread if it is already done when the
  callback is added.
- **on_done**: a callback the caller passes, run once on the ROS thread.
- **on_event**: a callback the caller passes, run on the ROS thread for each step of a goal.

Callbacks run on the ROS thread, so they must be cheap and thread-safe: the UI's only hand the
answer to the UI thread (an entry's `post(fn)`, the app's `post_message`). Nothing in a callback
may touch textual directly. An answer can arrive before the request returns, so a caller sets up
whatever its callback needs before it asks.

FakeBridge has no ROS thread: it answers on the thread that asks, or on the one that advances its
clock. Canned, its Futures are done when returned (call_service's never settles unless a test
settles it) and node requests answer before they return; live, answers wait for the clock.

On RosBridge, a request (any member that answers through a Future, on_done or on_event) made
before `start()`, after `shutdown()` or after the ROS thread stopped raises RuntimeError at once.
At shutdown, a request still waiting for its server or its response fails with "ROS bridge shut
down" (a Future gets the RuntimeError, an on_done the text, an on_event an ERROR event). A request
still queued for the ROS thread is dropped: call_service's Future fails with that RuntimeError,
the other Futures are cancelled, and a callback never runs. A goal already sent gets no ERROR:
shutdown cancels it, and its on_event sees the RESULT only if the server answers within
SHUTDOWN_CANCEL_TIMEOUT_S.

`time_setters` are the `stamp: now` / `header: auto` setters `message_yaml.build_message` returns;
the bridge calls each with the current ROS time on the ROS thread right before every send.
"""

from concurrent.futures import Future
from typing import Any, Callable, Protocol

from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.events import ActionEvent
from ros_tui.ros.graph import GraphSnapshot, NodeInfo
from ros_tui.ros.message_yaml import TimeSetter
from ros_tui.ros.parameters import Param

GraphListener = Callable[[GraphSnapshot], None]
ActionEventCallback = Callable[[ActionEvent], None]
NodeInfoDone = Callable[[NodeInfo | None, str | None], None]  # (info, error): exactly one is None.
ParametersDone = Callable[[list[Param] | None, str | None], None]  # (params, error): one is None.
SetParameterDone = Callable[[str | None], None]  # (error): None when the node accepted the value.


class Bridge(Protocol):
    """The UI's only way to ROS. See the module docstring for how answers arrive."""

    # ---------------------------------------------------------------- clock + graph

    def now(self) -> float:
        """The UI's clock: monotonic seconds. Safe from any thread. FakeBridge's is simulated."""
        ...

    def time_of_day(self) -> float:
        """Local seconds since midnight, for an activity line's "09:41:03". Safe from any thread."""
        ...

    @property
    def latest_graph(self) -> GraphSnapshot:
        """The newest graph snapshot (polled once a second). Safe from any thread."""
        ...

    def set_graph_listener(self, listener: GraphListener | None) -> None:
        """Call `listener(snapshot)` on the ROS thread whenever the graph snapshot changes (not on
        every poll); None stops it. One listener at a time; it replaces the previous one."""
        ...

    # ---------------------------------------------------------------- services

    def call_service(
        self, name: str, type_name: str, request: Any, time_setters: tuple[TimeSetter, ...] = (),
    ) -> Future:
        """Call service `name` (`type_name` like 'example_interfaces/srv/AddTwoInts') with a built
        `request`. Future: the response message, or TimeoutError when no server appears within
        READY_TIMEOUT_S or no response arrives within RESPONSE_TIMEOUT_S, or the call's error."""
        ...

    # ---------------------------------------------------------------- actions

    def send_goal(
        self,
        name: str,
        type_name: str,
        goal: Any,
        on_event: ActionEventCallback,
        time_setters: tuple[TimeSetter, ...] = (),
    ) -> None:
        """Send `goal` to action `name`. on_event, per step: ACCEPTED or REJECTED, then FEEDBACK
        (payload: the feedback message) any number of times, then RESULT (payload: the result
        message, status: a GoalStatus); or ERROR (payload: why) at any point, which ends the goal:
        no server within READY_TIMEOUT_S, the server vanished for READY_TIMEOUT_S while
        executing, a goal is already in flight on `name` (one goal per action at a time), an
        unknown type, a failed request, or shutdown. The answers to `cancel_goal` arrive here
        too."""
        ...

    def cancel_goal(self, name: str) -> None:
        """Ask the server to cancel the accepted goal on `name`; nothing happens when there is none
        (a goal not yet ACCEPTED is not canceled: ask again once it is). Answers through that
        goal's on_event: CANCEL_ACCEPTED (its RESULT with status CANCELED follows),
        CANCEL_REJECTED, or ERROR (the cancel request failed; the goal goes on)."""
        ...

    # ---------------------------------------------------------------- topics

    def publish_once(
        self, name: str, type_name: str, message: Any, time_setters: tuple[TimeSetter, ...] = (),
    ) -> Future:
        """Publish `message` on topic `name` once. Future: None once published, or the error."""
        ...

    def start_periodic_publish(
        self,
        name: str,
        type_name: str,
        message: Any,
        rate_hz: float,
        time_setters: tuple[TimeSetter, ...] = (),
    ) -> Future:
        """Publish `message` on `name` every 1 / rate_hz s (time setters applied on every tick)
        until `stop_periodic_publish` or shutdown; replaces a repeat already running on `name`.
        Future: None once started, or the error."""
        ...

    def stop_periodic_publish(self, name: str) -> Future:
        """Stop the repeat on `name`, if any. Future: None once stopped."""
        ...

    def subscribe(self, name: str, type_name: str, buffer: EchoBuffer) -> Future:
        """Echo topic `name` into `buffer`: every message is pushed on the ROS thread, the UI
        drains it. The QoS adapts to the publishers present now (best effort if any is). A second
        subscribe to `name` keeps the first one and its buffer. Future: None once subscribed, or
        the error (an unknown type, say)."""
        ...

    def unsubscribe(self, name: str) -> Future:
        """Stop echoing `name`, if it is echoed. Future: None once done."""
        ...

    # ---------------------------------------------------------------- nodes

    def get_node_info(self, node_name: str, on_done: NodeInfoDone) -> None:
        """The endpoints of `node_name` (like `ros2 node info`). on_done(info, None), or
        on_done(None, error)."""
        ...

    def list_node_parameters(self, node_name: str, on_done: ParametersDone) -> None:
        """Every parameter of `node_name` as a `Param` (ros/parameters.py: its name, type label
        and value). on_done(params, None), or on_done(None, error) when the node's parameter
        services are not there within READY_TIMEOUT_S, don't respond within RESPONSE_TIMEOUT_S,
        or fail."""
        ...

    def set_node_parameter(
        self, node_name: str, name: str, value: Any, type_label: str, on_done: SetParameterDone,
    ) -> None:
        """Set parameter `name` on `node_name` to `value`, sent as `type_label`: the type the
        parameter was declared with (its `Param.type`), so [1, 2] for a double[] goes out as
        doubles and [] as that array type. on_done(None) when the node accepted it, else
        on_done(error): the node's reason, a value that type can't hold, or why the request failed
        (as with list_node_parameters, including no response within RESPONSE_TIMEOUT_S)."""
        ...

    # ---------------------------------------------------------------- lifecycle

    def shutdown(self) -> None:
        """Stop: cancel the running goals (as `ros2 action send_goal` does on ctrl+c), stop the
        repeats and echoes, and free every ROS entity. Waits for the ROS thread (3 s at most).
        Does nothing before start or a second time."""
        ...
