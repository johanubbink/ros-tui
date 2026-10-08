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

"""The action entry: a GOAL editor in field rows, and the RESULT of the last goal with its live
feedback.

Pure Python (no textual, no rclpy).

- space / ^s checks the goal and sends it (`send_goal`). Its events arrive on the bridge's thread:
  feedback is pushed into the goal's bounded buffer (an `EchoBuffer`), which every clock tick
  (`tick`) drains, keeping only the newest feedback (converted when shown). The other events
  (accepted, the result, a rejection or an error) are posted to the UI thread.
- **One goal runs at a time, app-wide**: while any goal executes, space on any action tab sends
  nothing and says so in an errline and a red activity line ("a goal is already running on /fibonacci", plus "— s cancels
  it" on that goal's own tab). The Send button looks disabled meanwhile.
- s cancels this entry's running goal (`cancel_goal`; one still on its way is canceled once the
  server accepts it); it never sends. Quitting cancels it too (`RosBridge.shutdown`).
- RESULT shows EXECUTING with the time on the bridge's clock and the newest feedback, then
  SUCCEEDED with the result, CANCELED with the last feedback, or ABORTED / REJECTED / FAILED.
- A running goal shows the ◐◓◑◒ spinner (`running`) in its tab, the top bar and the Here column,
  whether its tab is open or not, until it ends.

Editing, `[ ]` history and undo come from `MessageEntry`.
"""

from dataclasses import dataclass
from typing import Any

from ros_tui.constants import ACTION_SPINNER_HZ, FEEDBACK_BUFFER_MAXLEN
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.events import ActionEvent, ActionEventKind, goal_status_name
from ros_tui.ros.message_yaml import class_structure, message_to_display
from ros_tui.ui.entries.base import Area, Context, Running, Tab, Verb
from ros_tui.ui.entries.message import EDITOR, MessageEntry, Received
from ros_tui.ui.fields import Row, flat_rows
from ros_tui.ui.nav import NavState

RESULT = 'out'  # The area id of RESULT.
SPINNER = '◐◓◑◒'
SENDING, EXECUTING = 'SENDING', 'EXECUTING'  # A goal's states while it runs; then the result's status.
SUCCEEDED, CANCELED, REJECTED, FAILED = 'SUCCEEDED', 'CANCELED', 'REJECTED', 'FAILED'


def spinner(now: float) -> str:
    """The spinner's frame at clock time `now`."""
    return SPINNER[int(now * ACTION_SPINNER_HZ) % len(SPINNER)]


@dataclass
class Goal:
    """One goal of an action: running until it ends, then its status, result or error."""

    at: float  # Clock time it was sent.
    sent: str  # The goal, summarised.
    buffer: EchoBuffer  # Feedback, pushed on the bridge's thread and drained on the tick.
    state: str = SENDING  # SENDING, EXECUTING, then SUCCEEDED, CANCELED, ABORTED, REJECTED or FAILED.
    end: float | None = None  # Clock time it ended.
    feedback: Received | None = None  # The newest feedback.
    feedbacks: int = 0  # How many feedbacks arrived.
    result: dict | None = None  # The result, as display values.
    error: str = ''  # Why it was rejected or failed.
    canceling: bool = False  # s asked the server to cancel it.

    @property
    def running(self) -> bool:
        return self.state in (SENDING, EXECUTING)

    def elapsed(self, now: float) -> float:
        return (now if self.end is None else self.end) - self.at


class LastGoal:
    """The goal sent last, app-wide: every action entry shares the one in its `Context`. Only one
    goal runs at a time, so if any goal runs, it is this one."""

    def __init__(self):
        self.tab: Tab | None = None
        self.goal: Goal | None = None

    def running(self) -> Tab | None:
        """The entry whose goal runs now, if any."""
        return self.tab if self.goal is not None and self.goal.running else None


def finish_line(goal: Goal) -> tuple[str, str]:
    """The activity line (text, cls) of a goal that ended."""
    took = f'{goal.end - goal.at:.1f} s'
    if goal.state == SUCCEEDED:
        return f'✓ goal succeeded · {took}', 'g'
    if goal.state == CANCELED:
        return f'■ goal canceled after {took}', 'y'
    if goal.state == REJECTED:
        return '✗ goal rejected by the server', 'r'
    if goal.state == FAILED:
        return f'✗ goal failed: {goal.error}', 'r'
    return f'✗ goal {goal.state.lower()} after {took}', 'r'


class ActionEntry(MessageEntry):
    """An action: its GOAL editor and the RESULT of the last goal sent from it."""

    KIND = 'action'
    ROLE = 'goal'
    AREAS = (Area(EDITOR, 'GOAL', 'edit', True, folds=True, helpers=True), Area(RESULT, 'RESULT'))

    def __init__(self, tab: Tab, ctx: Context | None = None):
        super().__init__(tab, ctx)
        self.goal: Goal | None = None  # The last goal sent from this entry.
        self.seen: tuple = ()  # What the screen last showed of a running goal, so a tick redraws only on a change.
        self._last = self._ctx.single(LastGoal)

    def load_extra(self, interface: type) -> Any:
        """The feedback's and the result's structures, loaded with the goal's."""
        return class_structure(interface.Feedback), class_structure(interface.Result)

    # ---------- what runs ----------
    def executing(self) -> Tab | None:
        """The entry whose goal runs now, if any: at most one, app-wide."""
        return self._last.running()

    def running(self) -> tuple[Running, ...]:
        return (Running(spinner(self._bridge.now()), 'running', 'live'),) if self.goal and self.goal.running else ()

    def tick(self, nav: NavState) -> bool:
        """Drain the running goal's feedback. True when the screen shows something new: the
        spinner's frame (in the top bar on every tab), and on the goal's own tab its time or a new
        feedback. So a running goal redraws at most ACTION_SPINNER_HZ times a second elsewhere."""
        goal = self.goal
        if goal is None or not goal.running:
            return False
        self._take_feedback(goal)
        now, here = self._bridge.now(), self.tab == nav.tab
        seen = (spinner(now), f'{goal.elapsed(now):.1f}' if here else None, goal.feedbacks if here else None)
        if seen == self.seen:
            return False
        self.seen = seen
        return True

    @staticmethod
    def _take_feedback(goal: Goal) -> None:
        messages, received, _, _ = goal.buffer.drain()
        if messages:
            goal.feedback = Received(messages[-1])
        goal.feedbacks = received

    # ---------- RESULT ----------
    def result_rows(self) -> tuple[str, list[Row]]:
        """What RESULT shows of the last goal: ('feedback', rows) while it runs and after a cancel
        (the last feedback), ('result', rows) once it ended otherwise, or ('', []) for nothing."""
        goal = self.goal
        if goal is None or self.extra is None:
            return '', []
        feedback_fields, result_fields = self.extra
        if goal.running or (goal.state == CANCELED and goal.feedback is not None):
            return 'feedback', flat_rows(feedback_fields, goal.feedback.display) if goal.feedback is not None else []
        if goal.result is not None:
            return 'result', flat_rows(result_fields, goal.result)
        return '', []

    def row_count(self, area: Area) -> int:
        if area.id == RESULT:
            return len(self.result_rows()[1])
        return super().row_count(area)

    # ---------- verbs ----------
    def verbs(self) -> dict[str, Verb]:
        return {**super().verbs(), 'primary': lambda nav, how, _: self._send_goal(nav, how),
                'secondary': lambda nav, how, _: self._cancel(nav, how)}

    def _send_goal(self, nav: NavState, how: str) -> None:
        """space / ^s: check the goal and send it, unless a goal runs already (on any action)."""
        tab = self.tab
        running = self.executing()
        if running is not None:
            own = ' — s cancels it' if running == tab else ''
            nav.feedback.report_error(tab, f'a goal is already running on {running.name}{own}')
            nav.feedback.log_line(how, 'a goal is already running')
            return
        ready = self._send(nav, how, '▶ goal sent', 'c', f'sent a goal to {tab.name}')
        if ready is None:
            return
        message, time_setters, sent = ready
        goal = self.goal = Goal(self._bridge.now(), sent, EchoBuffer(FEEDBACK_BUFFER_MAXLEN, clock=self._bridge.now))
        self._last.tab, self._last.goal = tab, goal
        self._bridge.send_goal(tab.name, self.type, message, lambda event: self._event(nav, goal, event), time_setters)

    def _cancel(self, nav: NavState, how: str) -> None:
        """s: ask the server to cancel this entry's running goal. It never sends a goal."""
        goal = self.goal
        if goal is None or not goal.running:
            running = self.executing()
            nav.feedback.log_line(how, f'nothing running here — the goal runs on {running.name}' if running
                                  else 'nothing running here')
            return
        if goal.canceling:
            nav.feedback.log_line(how, 'already canceling — waiting for the server')
            return
        goal.canceling = True
        nav.feedback.clear_error(self.tab)  # "a goal is already running" is about to be over.
        if goal.state == SENDING:  # The bridge can only cancel an accepted goal: _update does it then.
            nav.feedback.log_line(how, 'canceling the goal once the server accepts it')
            return
        nav.feedback.log_line(how, 'canceling the goal')
        self._bridge.cancel_goal(self.tab.name)

    # ---------- the goal's events ----------
    def _event(self, nav: NavState, goal: Goal, event: ActionEvent) -> None:
        """On the bridge's thread: feedback goes into the goal's buffer (the tick drains it); the
        other events are timed, made plain data and applied on the UI thread."""
        if event.kind == ActionEventKind.FEEDBACK:
            goal.buffer.push(event.payload)
            return
        now = self._bridge.now()
        result = message_to_display(event.payload) if event.kind == ActionEventKind.RESULT and event.payload else None
        self._post(lambda: self._update(nav, goal, event, now, result))

    def _update(self, nav: NavState, goal: Goal, event: ActionEvent, now: float, result: dict | None) -> None:
        kind = event.kind
        if goal.end is not None:
            return  # It ended already; a late event changes nothing.
        if kind == ActionEventKind.ACCEPTED:
            goal.state = EXECUTING
            if goal.canceling:  # s came while it was on its way.
                self._bridge.cancel_goal(self.tab.name)
            return
        if kind == ActionEventKind.CANCEL_ACCEPTED:
            return  # The CANCELED result follows.
        if kind == ActionEventKind.CANCEL_REJECTED:
            goal.canceling = False
            nav.feedback.add_activity(self.tab, '✗ the server would not cancel the goal', 'r')
            return
        self._take_feedback(goal)
        goal.end = now
        if kind == ActionEventKind.RESULT:
            goal.state, goal.result = goal_status_name(event.status), result
        elif kind == ActionEventKind.REJECTED:
            goal.state, goal.error = REJECTED, 'the server rejected the goal'
        else:
            goal.state, goal.error = FAILED, str(event.payload or 'unknown error')
        nav.feedback.add_activity(self.tab, *finish_line(goal))
