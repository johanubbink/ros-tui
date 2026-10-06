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

Pure Python (no textual, no rclpy), as the design's actions branches of send(), secondary() and
renderEntry, and its goal progression timer.

- space / ^s checks the goal and sends it (`send_goal`). Its events arrive on the bridge's thread:
  feedback is pushed into the goal's bounded buffer (an `EchoBuffer`), which every clock tick
  (`tick`) drains, keeping only the newest feedback, converted once. The other events (accepted,
  the result, a rejection or an error) are posted to the UI thread.
- **One goal runs at a time, app-wide** (the design's S.goal): while any goal executes, space on any
  action tab sends nothing and says so in an errline and a red activity line ("a goal is already
  running on /fibonacci", plus "— s cancels it" on that goal's own tab). The Send button looks
  disabled meanwhile.
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

from ros_tui.constants import ACTION_SPINNER_HZ, FEEDBACK_BUFFER_MAXLEN, SUMMARY_MAX_CHARS
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.events import ActionEvent, ActionEventKind, goal_status_name
from ros_tui.ros.message_yaml import class_structure, message_to_display
from ros_tui.ui.entries.message import MessageData, MessageEntry
from ros_tui.ui.fields import Row, flat_rows, summary
from ros_tui.ui.nav import Area, NavState, Running, Tab

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
    feedback: dict | None = None  # The newest feedback, as display values.
    feedbacks: int = 0  # How many feedbacks arrived.
    result: dict | None = None  # The result, as display values.
    error: str = ''  # Why it was rejected or failed.
    canceling: bool = False  # s asked the server to cancel it.

    @property
    def running(self) -> bool:
        return self.state in (SENDING, EXECUTING)

    def elapsed(self, now: float) -> float:
        return (now if self.end is None else self.end) - self.at


@dataclass
class ActionData(MessageData):
    goal: Goal | None = None  # The last goal sent from this entry.
    seen: tuple = ()  # What the screen last showed of a running goal, so a tick redraws only on a change.


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
    """The action entry kind. It holds every action tab, so it knows the one goal that runs."""

    KIND = 'action'

    def new_data(self) -> ActionData:
        return ActionData()

    def load_extra(self, interface: type) -> Any:
        """The feedback's and the result's structures, loaded with the goal's."""
        return class_structure(interface.Feedback), class_structure(interface.Result)

    # ---------- what runs ----------
    def executing(self) -> Tab | None:
        """The entry whose goal runs now, if any: at most one, app-wide."""
        return next((Tab.of(key) for key, data in self._data.items() if data.goal and data.goal.running), None)

    def running(self) -> dict[Tab, tuple[Running, ...]]:
        tab = self.executing()
        return {tab: (Running(spinner(self._bridge.now()), 'running', 'live'),)} if tab else {}

    def tick(self, nav: NavState) -> bool:
        """Drain the running goal's feedback. True when the screen shows something new: the
        spinner's frame (in the top bar on every tab), and on the goal's own tab its time or a new
        feedback. So a running goal redraws at most ACTION_SPINNER_HZ times a second elsewhere."""
        tab = self.executing()
        if tab is None:
            return False
        data = self.data(tab)
        goal = data.goal
        self._take_feedback(goal)
        now, here = self._bridge.now(), tab == nav.tab
        seen = (spinner(now), f'{goal.elapsed(now):.1f}' if here else None, goal.feedbacks if here else None)
        if seen == data.seen:
            return False
        data.seen = seen
        return True

    @staticmethod
    def _take_feedback(goal: Goal) -> None:
        messages, received, _, _ = goal.buffer.drain()
        if messages:
            goal.feedback = message_to_display(messages[-1])
        goal.feedbacks = received

    # ---------- RESULT ----------
    def result_rows(self, tab: Tab) -> tuple[str, list[Row]]:
        """What RESULT shows of the last goal: ('feedback', rows) while it runs and after a cancel
        (the last feedback), ('result', rows) once it ended otherwise, or ('', []) for nothing."""
        data = self.data(tab)
        goal = data.goal
        if goal is None or data.extra is None:
            return '', []
        feedback_fields, result_fields = data.extra
        if goal.running or (goal.state == CANCELED and goal.feedback is not None):
            return 'feedback', flat_rows(feedback_fields, goal.feedback) if goal.feedback is not None else []
        if goal.result is not None:
            return 'result', flat_rows(result_fields, goal.result)
        return '', []

    def row_count(self, tab: Tab, area: Area) -> int:
        if area.id == RESULT:
            return len(self.result_rows(tab)[1])
        return super().row_count(tab, area)

    # ---------- verbs ----------
    def verb(self, nav: NavState, tab: Tab | None, name: str, how: str, arg: Any = None) -> bool:
        if name == 'primary':
            self.send(nav, tab, how)
        elif name == 'secondary':
            self.cancel(nav, tab, how)
        else:
            return super().verb(nav, tab, name, how, arg)
        return True

    def send(self, nav: NavState, tab: Tab, how: str) -> None:
        """space / ^s: check the goal and send it, unless a goal runs already (on any action)."""
        running = self.executing()
        if running is not None:
            own = ' — s cancels it' if running == tab else ''
            nav.report_error(tab, f'a goal is already running on {running.name}{own}')
            nav.log_line(how, 'a goal is already running')
            return
        built = self.checked(nav, tab, how)
        if built is None:
            return
        message, time_setters = built
        data = self.data(tab)
        now = self._bridge.now()
        goal = data.goal = Goal(now, summary(self.remember(tab), SUMMARY_MAX_CHARS),
                                EchoBuffer(FEEDBACK_BUFFER_MAXLEN, clock=self._bridge.now))
        nav.errlines.pop(tab.key, None)
        nav.flash_send(tab)
        nav.add_activity(tab, f'▶ goal sent · {goal.sent}' if goal.sent else '▶ goal sent', 'c')
        nav.log_line(how, f'sent a goal to {tab.name}')
        self._bridge.send_goal(tab.name, data.type, message, lambda event: self._event(nav, tab, goal, event),
                               tuple(time_setters))

    def cancel(self, nav: NavState, tab: Tab, how: str) -> None:
        """s: ask the server to cancel this entry's running goal. It never sends a goal."""
        goal = self.data(tab).goal
        if goal is None or not goal.running:
            running = self.executing()
            nav.log_line(how, f'nothing running here — the goal runs on {running.name}' if running
                         else 'nothing running here')
            return
        if goal.canceling:
            nav.log_line(how, 'already canceling — waiting for the server')
            return
        goal.canceling = True
        nav.errlines.pop(tab.key, None)  # "a goal is already running" is about to be over.
        if goal.state == SENDING:  # The bridge can only cancel an accepted goal: _update does it then.
            nav.log_line(how, 'canceling the goal once the server accepts it')
            return
        nav.log_line(how, 'canceling the goal')
        self._bridge.cancel_goal(tab.name)

    # ---------- the goal's events ----------
    def _event(self, nav: NavState, tab: Tab, goal: Goal, event: ActionEvent) -> None:
        """On the bridge's thread: feedback goes into the goal's buffer (the tick drains it); the
        other events are timed, made plain data and applied on the UI thread."""
        if event.kind == ActionEventKind.FEEDBACK:
            goal.buffer.push(event.payload)
            return
        now = self._bridge.now()
        result = message_to_display(event.payload) if event.kind == ActionEventKind.RESULT and event.payload else None
        self._post(lambda: self._update(nav, tab, goal, event, now, result))

    def _update(self, nav: NavState, tab: Tab, goal: Goal, event: ActionEvent, now: float,
                result: dict | None) -> None:
        kind = event.kind
        if goal.end is not None:
            return  # It ended already; a late event changes nothing.
        if kind == ActionEventKind.ACCEPTED:
            goal.state = EXECUTING
            if goal.canceling:  # s came while it was on its way.
                self._bridge.cancel_goal(tab.name)
            return
        if kind == ActionEventKind.CANCEL_ACCEPTED:
            return  # The CANCELED result follows.
        if kind == ActionEventKind.CANCEL_REJECTED:
            goal.canceling = False
            nav.add_activity(tab, '✗ the server would not cancel the goal', 'r')
            return
        self._take_feedback(goal)
        goal.end = now
        if kind == ActionEventKind.RESULT:
            goal.state, goal.result = goal_status_name(event.status), result
        elif kind == ActionEventKind.REJECTED:
            goal.state, goal.error = REJECTED, 'the server rejected the goal'
        else:
            goal.state, goal.error = FAILED, str(event.payload or 'unknown error')
        nav.add_activity(tab, *finish_line(goal))
