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

"""The topic entry: Echo (the LATEST MESSAGE, live or frozen) and Publish (a MESSAGE editor, sent
once or repeated at a rate). `e` switches between them.

Pure Python (no textual, no rclpy).

Echo:
- space / ^s starts the echo (`subscribe` into an `EchoBuffer` timed by the bridge's clock) or
  stops it. It keeps running in other tabs, and shows as ◉ (`running`).
- Every clock tick (`tick`) drains the buffers. Only the newest message is kept; it is converted
  to display values (`Received`) only when LATEST MESSAGE shows it. The tick also keeps the
  count, the dropped messages and the rate (over the buffer's last arrivals).
- Going inside LATEST MESSAGE freezes what it shows; new messages are only counted ("+N new
  since"). Leaving it, however that happens, makes it live again: being frozen is not stored, it
  is where the cursor is (`frozen`).
- enter on a field hides or shows it, per entry.
- y copies the message LATEST MESSAGE shows (the frozen one while frozen) into the register. The
  newest message is also kept as it arrived, so the copy is exact, not cut for display.

Publish (the editor, history and undo come from `MessageEntry`):
- space / ^s publishes the message once; r repeats it at the rate (`start_periodic_publish`) until
  s stops it, showing ↻. The repeat sends the message as it was when r was pressed.
- R (or `:rate 5`) changes the rate, 0.1–100 Hz; a change is one undo step and restarts a running
  repeat at the new rate. Until it is changed, the rate is the publisher's, as the echo measured it,
  or PUBLISH_DEFAULT_RATE_HZ.
"""

from dataclasses import dataclass
from typing import Any

from ros_tui.constants import PUBLISH_DEFAULT_RATE_HZ, PUBLISH_RATE_MAX_HZ, PUBLISH_RATE_MIN_HZ
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.message_yaml import message_to_plain
from ros_tui.ui.entries.base import Area, Commit, Context, Editing, Running, Tab, UndoEntry, Verb
from ros_tui.ui.entries.message import EDITOR, MessageEntry, Received
from ros_tui.ui.fields import Row, flat_rows
from ros_tui.ui.nav import AREA, EDIT, IN, NavState
from ros_tui.ui.register import Register

ECHO = 'out'  # The area id of LATEST MESSAGE.
RATE = 'rate'  # The Editing area of the rate editor.
ECHOING = Running('◉', 'echoing', 'live')
RATE_RANGE = f'{PUBLISH_RATE_MIN_HZ:g}–{PUBLISH_RATE_MAX_HZ:g} Hz'  # The rates a repeat takes.


@dataclass
class Echo:
    """A running echo: its buffer and what the last drain said."""

    buffer: EchoBuffer
    received: int = 0  # Messages received since it started.
    dropped: int = 0  # Of those, how many the buffer dropped before a drain took them.
    hz: float = 0.0  # The receive rate over the buffer's last arrivals.


@dataclass
class Repeat:
    """A running repeat: the message it sends and since when, at which rate."""

    message: Any
    time_setters: tuple
    rate: float
    since: float  # Clock time it started, or its rate last changed.
    sent_before: int = 0  # Sent at earlier rates.

    def sent(self, now: float) -> int:
        return self.sent_before + int((now - self.since) * self.rate + 1e-9)


def rate_text(rate: float) -> str:
    return f'{rate:g}'


def parse_rate(text: str) -> float:
    """A typed repeat rate, or ValueError with the user's message."""
    try:
        rate = float(text)
    except ValueError:
        rate = None
    if rate is None or not PUBLISH_RATE_MIN_HZ <= rate <= PUBLISH_RATE_MAX_HZ:
        raise ValueError(f'rate must be {RATE_RANGE}, got "{text.strip()}"')
    return rate


class TopicEntry(MessageEntry):
    """A topic, in Echo or Publish (its `mode`)."""

    KIND = 'msg'
    ROLE = 'message'
    MODES = {'echo': (Area(ECHO, 'LATEST MESSAGE', 'show / hide field'),),
             'publish': (Area(EDITOR, 'MESSAGE', 'edit', True, folds=True, helpers=True),)}

    def __init__(self, tab: Tab, ctx: Context | None = None):
        super().__init__(tab, ctx)
        self.echo: Echo | None = None
        self.latest: Received | None = None  # The newest message received.
        self.shown: Received | None = None  # What LATEST MESSAGE shows: the newest, or what it froze on.
        self.new_since = 0  # Messages received since it froze.
        self.hidden: set[str] = set()  # Echo rows (field paths) hidden with enter.
        self.chosen_rate: float | None = None  # The repeat rate the user set (None: not set).
        self.measured = 0.0  # The publisher's rate, as the echo last measured it.
        self.repeat: Repeat | None = None
        self.seen: tuple = ()  # What the toolbar last showed (echo counts, repeat sent), so a tick redraws only on a change.

    # ---------- opening ----------
    def on_open(self, nav: NavState) -> None:
        """Load the message type (MessageEntry). The mode it first opens in (Echo when someone
        publishes) comes from the ☰ list's counts."""
        if not self.mode:
            self.mode = 'echo' if self.publishers(nav) > 0 else 'publish'
        super().on_open(nav)

    def counts(self, nav: NavState) -> tuple[int, int] | None:
        """(publishers, subscribers) as the graph last counted them; None when the graph lost the topic."""
        item = nav.catalog.item(self.tab)
        return (item.publishers, item.subscribers) if item else None

    def publishers(self, nav: NavState) -> int:
        counts = self.counts(nav)
        return counts[0] if counts else 0

    # ---------- the rate ----------
    def rate(self) -> float:
        """The repeat rate: the user's, else the publisher's as measured, else the default."""
        if self.chosen_rate is not None:
            return self.chosen_rate
        if self.measured:
            return min(PUBLISH_RATE_MAX_HZ, max(PUBLISH_RATE_MIN_HZ, round(self.measured, 1)))
        return PUBLISH_DEFAULT_RATE_HZ

    def rate_note(self) -> str:
        if self.chosen_rate is not None:
            return 'your rate'
        return 'matches the publisher' if self.measured else 'default'

    def label_vars(self) -> dict[str, Any]:
        return {'rate': rate_text(self.rate())}

    def _apply_rate(self, rate: float | None) -> str:
        """Set the user's rate (None: back to the default one) and restart a running repeat at it.
        Returns the activity line of a restarted repeat, or ''."""
        self.chosen_rate = rate
        repeat = self.repeat
        if repeat is None or repeat.rate == self.rate():
            return ''
        now = self._bridge.now()
        repeat.sent_before, repeat.since, repeat.rate = repeat.sent(now), now, self.rate()
        self._bridge.start_periodic_publish(self.tab.name, self.type, repeat.message, repeat.rate, repeat.time_setters)
        return f'↻ rate now {rate_text(repeat.rate)} Hz'

    def _set_rate(self, rate: float) -> tuple[UndoEntry | None, str]:
        """A new rate: (its undo step, None when it didn't change; the activity line)."""
        if rate == self.rate():
            return None, ''
        before = self.chosen_rate

        def revert(nav: NavState) -> str:
            activity = self._apply_rate(before)
            if activity:
                nav.feedback.add_activity(self.tab, activity, 'g')
            return f'repeat rate on {self.tab.name} back to {rate_text(self.rate())} Hz'
        return UndoEntry(self.tab, revert), self._apply_rate(rate)

    def _edit_rate(self, nav: NavState, how: str) -> None:
        """R: type a new rate in place of the shown one (from Echo, switch to Publish first, so esc
        goes back to the area pick)."""
        back = None
        if self.mode != 'publish':
            self.mode, back = 'publish', IN
        text = rate_text(self.rate())
        nav.begin_edit(Editing(RATE, 0, text, old=text, fresh=True, field='repeat rate',
                               note='(type a number, enter keeps it)', crumb=('repeat rate',), back=back))
        nav.feedback.log_line(how, 'editing the repeat rate: type a number, enter keeps it')

    def _command_rate(self, nav: NavState, how: str, text: str) -> None:
        """:rate 5"""
        tab = self.tab
        try:
            rate = parse_rate(text)
        except ValueError as error:
            nav.feedback.report_error(tab, str(error))
            nav.feedback.refuse(how, f'{error} — usage: :rate 5', 'rate not changed')
            return
        undo, activity = self._set_rate(rate)
        if undo:
            nav.push_undo(undo)
        if activity:
            nav.feedback.add_activity(tab, activity, 'g')
        nav.feedback.clear_error(tab)
        nav.feedback.show_toast(f'repeat rate {rate_text(rate)} Hz', 'info')
        nav.feedback.log_line(how, f'repeat rate on {tab.name} is {rate_text(rate)} Hz' + (' (u undoes)' if undo else ''))

    def commit_edit(self, editing: Editing) -> Commit:
        if editing.area != RATE:
            return super().commit_edit(editing)
        try:
            rate = parse_rate(editing.value)
        except ValueError as error:
            return Commit(False, str(error))
        running = self.repeat is not None
        undo, activity = self._set_rate(rate)
        text = f'repeat rate {rate_text(rate)} Hz' + (' (applied to the running repeat)' if running else '')
        return Commit(True, text + (' (u undoes)' if undo else ''), undo, (activity, 'g') if activity else ())

    # ---------- rows ----------
    def echo_rows(self, nav: NavState) -> list[Row]:
        """LATEST MESSAGE: one row per field, with the values it shows: the newest message, or the
        one it froze on (None before the first message)."""
        if self.editor is None:
            return []
        received = self.received(nav)
        return flat_rows(self.editor.fields, received.display if received else None)

    def received(self, nav: NavState) -> Received | None:
        """The message LATEST MESSAGE shows: the one it froze on while frozen, else the newest."""
        return self.shown if self.frozen(nav) else self.latest

    def row_count(self, area: Area) -> int:
        if area.id == ECHO:
            return len(flat_rows(self.editor.fields, None)) if self.editor else 0
        return super().row_count(area)

    def activate_row(self, nav: NavState, area: Area, row: int, how: str) -> bool:
        """enter on an echoed field hides or shows it."""
        if area.id != ECHO:
            return super().activate_row(nav, area, row, how)
        rows = self.echo_rows(nav)
        if not 0 <= row < len(rows):
            return False
        hidden, name = self.hidden, rows[row].field
        hidden.symmetric_difference_update({name})
        nav.feedback.log_line(how, f'{"hid" if name in hidden else "showing"} {name}')
        return True

    # ---------- echo: live and frozen ----------
    def frozen(self, nav: NavState) -> bool:
        """An echo is frozen while the cursor is inside its LATEST MESSAGE."""
        area = nav.area()
        inside = nav.layer in (AREA, EDIT) and area is not None and area.id == ECHO
        return inside and nav.tab == self.tab and self.mode == 'echo' and self.echo is not None

    def leave_area(self, area: Area) -> str | None:
        if area.id == ECHO and self.echo is not None:
            return 'out of the latest message: values are live again'
        return None

    def esc_label(self, area: Area) -> str | None:
        return 'go live' if area.id == ECHO and self.echo is not None else None

    def tick(self, nav: NavState) -> bool:
        """Drain a running echo: keep the newest message, count, rate, drops; a
        frozen echo only counts what arrived. True when the active tab shows something new: its
        echo's count or rate, or its repeat's sent count. An echo or repeat in another tab changes
        nothing on screen (its markers only change on start and stop), so it doesn't redraw."""
        echo = self.echo
        if echo is not None:
            messages, received, dropped, hz = echo.buffer.drain()
            fresh = received - echo.received
            echo.received, echo.dropped, echo.hz = received, dropped, hz
            if hz > 0:
                self.measured = hz
            if messages:
                self.latest = Received(messages[-1])
            if self.frozen(nav):
                self.new_since += fresh
            else:
                self.shown, self.new_since = self.latest, 0
        seen = ((echo.received, f'{echo.hz:.1f}', echo.dropped) if echo else None,
                self.repeat.sent(self._bridge.now()) if self.repeat else None)
        changed = self.tab == nav.tab and seen != self.seen
        self.seen = seen
        return changed

    def _toggle_echo(self, nav: NavState, how: str) -> None:
        """space in Echo: start the echo, or stop it."""
        tab = self.tab
        if self.echo is not None:
            self._stop_echo(nav)
            nav.feedback.log_line(how, 'stopped echo')
            return
        if not self.type:
            nav.feedback.refuse(how, f'no type information for {tab.name}', 'nothing to echo')
            return
        self.echo = Echo(EchoBuffer(clock=self._bridge.now))
        future = self._bridge.subscribe(tab.name, self.type, self.echo.buffer)
        future.add_done_callback(lambda done: self._failed(nav, done, 'echo', 'echo'))
        nav.feedback.add_activity(tab, '◉ echo started', 'c')
        nav.feedback.log_line(how, 'started echo')

    def _stop_echo(self, nav: NavState) -> None:
        self._bridge.unsubscribe(self.tab.name)
        self.echo, self.latest, self.shown, self.new_since = None, None, None, 0
        nav.feedback.add_activity(self.tab, '■ echo stopped', 'dim')

    def _yank_echo(self, nav: NavState, how: str) -> None:
        """y in Echo: copy the message LATEST MESSAGE shows (the frozen one while frozen), exactly."""
        tab, received = self.tab, self.received(nav)
        if self.echo is None:
            problem = 'start the echo first (space)'
        elif received is None:
            problem = (f'no messages to copy: nobody publishes {tab.name}' if self.publishers(nav) == 0
                       else f'no messages to copy yet: waiting for the first one on {tab.name}')
        else:
            problem = ''
        if problem:
            nav.feedback.refuse(how, problem, 'nothing to copy yet')
            return
        nav.register = Register.of(self.type, self.ROLE, tab.name, message_to_plain(received.message))
        which = 'frozen' if self.frozen(nav) else 'latest'
        nav.feedback.show_toast(f'copied the {which} {nav.register.label} from {tab.name}', 'info')
        nav.feedback.log_line(how, f'copied the {which} message — p pastes it into an editor of the same type')

    # ---------- publish ----------
    def _publish(self, nav: NavState, how: str) -> None:
        """space in Publish: check the message, then publish it once."""
        ready = self._send(nav, how, '✓ published', 'g', f'published once on {self.tab.name}')
        if ready is None:
            return
        message, time_setters, _ = ready
        future = self._bridge.publish_once(self.tab.name, self.type, message, time_setters)
        future.add_done_callback(lambda done: self._failed(nav, done, 'publish'))

    def _start_repeat(self, nav: NavState, how: str) -> None:
        """r: publish the message at the rate until s stops it."""
        if self.repeat is not None:
            nav.feedback.show_toast(f'already repeating at {rate_text(self.repeat.rate)} Hz — s stops it', 'info')
            nav.feedback.log_line(how, 'already repeating')
            return
        ready = self._ready(nav, how)
        if ready is None:
            return
        message, time_setters, _ = ready
        rate = self.rate()
        self.repeat = Repeat(message, time_setters, rate, self._bridge.now())
        future = self._bridge.start_periodic_publish(self.tab.name, self.type, message, rate, time_setters)
        future.add_done_callback(lambda done: self._failed(nav, done, 'repeat', 'repeat'))
        nav.feedback.add_activity(self.tab, f'↻ repeating at {rate_text(rate)} Hz', 'g')
        nav.feedback.log_line(how, f'repeating at {rate_text(rate)} Hz')

    def _stop(self, nav: NavState, how: str) -> None:
        """s: stop the repeat. It never sends."""
        if self.repeat is None:
            nav.feedback.log_line(how, 'nothing running here')
            return
        self._stop_repeat(nav)
        nav.feedback.log_line(how, 'stopped repeating')

    def _stop_repeat(self, nav: NavState) -> None:
        self._bridge.stop_periodic_publish(self.tab.name)
        sent = self.repeat.sent(self._bridge.now())
        self.repeat = None
        nav.feedback.add_activity(self.tab, f'■ repeat stopped after {sent} sent', 'dim')

    def on_close(self, nav: NavState) -> list[str]:
        """Closing the tab stops its echo and its repeat: nothing would be left to stop them from."""
        stopped = []
        if self.echo is not None:
            self._stop_echo(nav)
            stopped.append('echo stopped')
        if self.repeat is not None:
            self._stop_repeat(nav)
            stopped.append('repeat stopped')
        return stopped

    def _failed(self, nav: NavState, future: Any, what: str, running: str = '') -> None:
        """On the bridge's thread: a subscribe or publish that failed says so (and forgets the
        `running` echo or repeat it started)."""
        error = None if future.cancelled() else future.exception()
        if error is None:
            return

        def report():
            if running:
                setattr(self, running, None)
            nav.feedback.add_activity(self.tab, f'✗ {what} failed: {error}', 'r')
        self._post(report)

    # ---------- running ----------
    def running(self) -> tuple[Running, ...]:
        return ((ECHOING,) if self.echo else ()) + (
            (Running('↻', f'{rate_text(self.repeat.rate)} Hz', 'ok'),) if self.repeat else ())

    # ---------- verbs ----------
    def verbs(self) -> dict[str, Verb]:
        """The editor's verbs, the rate's, then those of the mode: Echo's start / stop the echo and
        copy what it shows; Publish's publish once, repeat and stop."""
        verbs = {**super().verbs(),
                 'rate': lambda nav, how, _: self._edit_rate(nav, how),
                 'set_rate': lambda nav, how, arg: self._command_rate(nav, how, arg or '')}
        if self.mode == 'echo':
            verbs.update({
                'primary': lambda nav, how, _: self._toggle_echo(nav, how),
                'secondary': lambda nav, how, _: nav.feedback.log_line(
                    how, 'space stops the echo; going into the latest message freezes it'),
                'repeat': lambda nav, how, _: nav.feedback.log_line(how, 'r repeats a publish — e switches to Publish'),
                'history_older': self._history_is_for_publish,
                'history_newer': self._history_is_for_publish,
                'yank': lambda nav, how, _: self._yank_echo(nav, how),
                'paste': self._paste_in_echo,
            })
        else:
            verbs.update({
                'primary': lambda nav, how, _: self._publish(nav, how),
                'secondary': lambda nav, how, _: self._stop(nav, how),
                'repeat': lambda nav, how, _: self._start_repeat(nav, how),
            })
        return verbs

    @staticmethod
    def _history_is_for_publish(nav: NavState, how: str, _: Any) -> None:
        nav.feedback.log_line(how, 'the history is for Publish — e switches to it')

    def _paste_in_echo(self, nav: NavState, how: str, _: Any) -> None:
        if nav.register is None:
            self._paste(nav, how)  # It says nothing is copied yet.
        else:
            nav.feedback.refuse(how, 'switch to Publish (e) to paste', 'no editor in Echo')
