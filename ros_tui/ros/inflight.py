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
The bridge's requests in flight, and when each one fails.

Pure: no rclpy import. Entities, futures and goal handles are duck-typed: a server-ready check
is any callable, a response future anything with ``add_done_callback``, a client anything with
``remove_pending_request`` (rclpy's ``Client``) and an action client anything with
``server_is_ready``. Time comes from the clock passed in, so tests drive it by hand.

Three kinds of request are tracked:

- a **wait for a server**: a request whose server isn't up yet is parked; ``housekeep`` sends it
  once the server appears, or fails it after ``READY_TIMEOUT_S``;
- a **response**: a sent request fails after ``RESPONSE_TIMEOUT_S`` without a reply. A reply
  that lands after its request timed out or ``fail_all`` ran is ignored;
- a **goal**, from send until its result: one per action name. A goal whose action server is
  gone for ``READY_TIMEOUT_S`` ends with an ERROR event.

An entity any of these still uses is ``busy``, so the entity cache won't destroy it. Not
thread-safe: the bridge uses it on the ROS thread only, and every callback runs there too.
"""

import contextlib
import time
from dataclasses import dataclass
from typing import Any, Callable

from ros_tui.constants import READY_TIMEOUT_S, RESPONSE_TIMEOUT_S
from ros_tui.ros.events import ActionEvent, ActionEventKind

Fail = Callable[[Exception], None]


@dataclass(eq=False)
class _Wait:
    entity: Any
    is_ready: Callable[[], bool]
    dispatch: Callable[[], None]
    fail: Fail
    deadline: float
    label: str


@dataclass(eq=False)
class _Response:
    client: Any
    future: Any
    deadline: float
    label: str
    on_fail: Fail | None


@dataclass(eq=False)
class Goal:
    """A goal sent on one action, from send until its result."""

    client: Any
    on_event: Callable[[ActionEvent], None]
    handle: Any = None  # The server's goal handle, once it accepted the goal.
    server_lost_since: float | None = None  # When server_is_ready first turned false.


class Inflight:
    """The waits for a server, the responses and the goals the bridge has in flight."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._waits: list[_Wait] = []
        self._responses: list[_Response] = []
        self._goals: dict[str, Goal] = {}

    # ---------------------------------------------------------------- requests

    def wait_for_server(
        self,
        entity: Any,
        is_ready: Callable[[], bool],
        dispatch: Callable[[], None],
        fail: Fail,
        label: str,
    ) -> None:
        """``dispatch()`` now if ``is_ready()``, else park it until the server appears.

        A parked request whose server doesn't appear within READY_TIMEOUT_S gets
        ``fail(TimeoutError)``; one whose ready check or dispatch raises gets ``fail(error)``.
        """
        if is_ready():
            dispatch()
            return
        deadline = self._clock() + READY_TIMEOUT_S
        self._waits.append(_Wait(entity, is_ready, dispatch, fail, deadline, label))

    def track_response(
        self,
        client: Any,
        future: Any,
        label: str,
        on_response: Callable[[Any], None],
        on_fail: Fail | None = None,
    ) -> None:
        """Run ``on_response(future)`` when ``client``'s request ``future`` completes.

        Past RESPONSE_TIMEOUT_S the request is dropped from ``client`` and ``on_fail`` gets a
        TimeoutError; ``fail_all`` gives ``on_fail`` its error. After either, a late reply is
        ignored: ``on_response`` runs at most once, and never after ``on_fail``.
        """
        record = _Response(client, future, self._clock() + RESPONSE_TIMEOUT_S, label, on_fail)
        self._responses.append(record)

        def on_done(done: Any) -> None:
            if record not in self._responses:
                return
            self._responses.remove(record)
            on_response(done)

        future.add_done_callback(on_done)

    # ---------------------------------------------------------------- goals

    def begin_goal(self, name: str, client: Any, on_event: Callable[[ActionEvent], None]) -> None:
        """A goal is on its way to ``name``'s server through ``client``."""
        self._goals[name] = Goal(client, on_event)

    def goal_accepted(self, name: str, handle: Any) -> None:
        """The server accepted the goal on ``name``; from now on its server is watched."""
        goal = self._goals.get(name)
        if goal is not None:
            goal.handle = handle

    def end_goal(self, name: str) -> None:
        """The goal on ``name`` ended (result, rejection or error); a no-op if there is none."""
        self._goals.pop(name, None)

    def goals(self) -> dict[str, Goal]:
        """Every goal in flight by action name, accepted or not (a copy)."""
        return dict(self._goals)

    # ---------------------------------------------------------------- questions and events

    def busy(self, entity: Any) -> bool:
        """Whether a parked request, an awaited response or a goal still uses ``entity``."""
        return (
            any(wait.entity is entity for wait in self._waits)
            or any(record.client is entity for record in self._responses)
            or any(goal.client is entity for goal in self._goals.values())
        )

    def housekeep(self) -> None:
        """Settle the waits for a server, end the goals whose server vanished and time out the
        responses past their deadline. The bridge calls it from its housekeeping timer."""
        now = self._clock()
        self._settle_waits(now)
        self._watch_goals(now)
        self._expire_responses(now)

    def fail_all(self, error: Exception) -> None:
        """Fail every parked request and every awaited response with ``error`` (shutdown).

        Goals stay: the bridge cancels them after this.
        """
        waits, self._waits = self._waits, []
        responses, self._responses = self._responses, []
        for wait in waits:
            with contextlib.suppress(Exception):
                wait.fail(error)
        for record in responses:
            if record.on_fail is not None:
                with contextlib.suppress(Exception):
                    record.on_fail(error)

    # ---------------------------------------------------------------- housekeeping

    def _settle_waits(self, now: float) -> None:
        waits, self._waits = self._waits, []
        still_waiting = []
        for wait in waits:
            try:
                if wait.is_ready():
                    wait.dispatch()
                elif now >= wait.deadline:
                    wait.fail(TimeoutError(f'{wait.label} not available (no server found)'))
                else:
                    still_waiting.append(wait)
            except Exception as error:  # noqa: BLE001 - one bad entry must not kill housekeeping
                with contextlib.suppress(Exception):
                    wait.fail(error)
        self._waits = still_waiting + self._waits

    def _watch_goals(self, now: float) -> None:
        """End an accepted goal whose action server has been gone for READY_TIMEOUT_S.

        An action server dying mid-goal would otherwise leave the goal executing forever (its
        result never comes) and block new sends on that action."""
        for name, goal in list(self._goals.items()):
            if goal.handle is None:
                continue
            if goal.client.server_is_ready():
                goal.server_lost_since = None
            elif goal.server_lost_since is None:
                goal.server_lost_since = now
            elif now - goal.server_lost_since >= READY_TIMEOUT_S:
                self._goals.pop(name, None)
                with contextlib.suppress(Exception):
                    goal.on_event(ActionEvent(
                        name,
                        ActionEventKind.ERROR,
                        payload='action server vanished while the goal was executing',
                    ))

    def _expire_responses(self, now: float) -> None:
        expired = [record for record in self._responses if now >= record.deadline]
        self._responses = [record for record in self._responses if now < record.deadline]
        for record in expired:
            with contextlib.suppress(Exception):
                record.client.remove_pending_request(record.future)
            if record.on_fail is not None:
                with contextlib.suppress(Exception):
                    record.on_fail(TimeoutError(
                        f'no response from {record.label} after {RESPONSE_TIMEOUT_S:.0f} s'
                    ))
