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

Pure Python (no textual, no rclpy), as the design's topics branches of primary(), secondary(),
repeat(), editRate() and renderEntry.

Echo:
- space / ^s starts the echo (`subscribe` into an `EchoBuffer` timed by the bridge's clock) or
  stops it. It keeps running in other tabs, and shows as ◉ (`running`).
- Every clock tick (`tick`) drains the buffers. Only the newest message is kept, as plain values
  with long arrays and strings cut (`message_to_display`), so a fast topic costs one conversion
  per tick. The tick also keeps the count, the dropped messages and the rate (over the buffer's
  last arrivals).
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

from dataclasses import dataclass, field
from typing import Any, NamedTuple

from ros_tui.constants import PUBLISH_DEFAULT_RATE_HZ, PUBLISH_RATE_MAX_HZ, PUBLISH_RATE_MIN_HZ, SUMMARY_MAX_CHARS
from ros_tui.ros.echo import EchoBuffer
from ros_tui.ros.message_yaml import message_to_display, message_to_plain
from ros_tui.ui.entries.message import MessageData, MessageEntry
from ros_tui.ui.fields import Row, flat_rows, summary
from ros_tui.ui.nav import AREA, EDIT, IN, Area, Commit, Editing, NavState, Running, Tab, UndoEntry
from ros_tui.ui.register import Register

ECHO = 'out'  # The area id of LATEST MESSAGE.
RATE = 'rate'  # The Editing area of the rate editor, and the UndoEntry kind of a rate change.
ECHOING = Running('◉', 'echoing', 'live')


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


class Received(NamedTuple):
    """An echoed message as it arrived (for an exact y) and as display values (converted once)."""
    message: Any
    display: dict


@dataclass
class TopicData(MessageData):
    counts: tuple[int, int] | None = None  # (publishers, subscribers), asked for when the tab opens.
    echo: Echo | None = None
    latest: Received | None = None  # The newest message received.
    shown: Received | None = None  # What LATEST MESSAGE shows: the newest, or what it froze on.
    new_since: int = 0  # Messages received since it froze.
    hidden: set[str] = field(default_factory=set)  # Echo rows (field paths) hidden with enter.
    rate: float | None = None  # The repeat rate the user set (None: not set).
    measured: float = 0.0  # The publisher's rate, as the echo last measured it.
    repeat: Repeat | None = None
    mode: str = ''  # 'echo' or 'publish', from the first time the tab opens.
    seen: tuple = ()  # What the toolbar last showed (echo counts, repeat sent), so a tick redraws only on a change.


def rate_text(rate: float) -> str:
    return f'{rate:g}'


def parse_rate(text: str) -> float:
    """A typed repeat rate, or ValueError with the user's message."""
    try:
        rate = float(text)
    except ValueError:
        rate = None
    if rate is None or not PUBLISH_RATE_MIN_HZ <= rate <= PUBLISH_RATE_MAX_HZ:
        raise ValueError(f'rate must be {PUBLISH_RATE_MIN_HZ:g}–{PUBLISH_RATE_MAX_HZ:g} Hz, got "{text.strip()}"')
    return rate


class TopicEntry(MessageEntry):
    """The topic entry kind."""

    KIND = 'msg'

    def new_data(self) -> TopicData:
        return TopicData()

    # ---------- opening ----------
    def on_open(self, nav: NavState, tab: Tab) -> None:
        """Load the message type (MessageEntry) and ask how many publish and subscribe, each time it opens.
        The mode it first opens in (Echo when someone publishes) comes from the ☰ list's counts."""
        data = self.data(tab)
        if not data.mode:
            item = nav.item(tab)
            data.mode = 'echo' if item and item.publishers > 0 else 'publish'
        super().on_open(nav, tab)
        future = self._bridge.topic_endpoint_counts(tab.name)
        future.add_done_callback(lambda done: self._counts_done(tab, done))

    def _counts_done(self, tab: Tab, future: Any) -> None:
        if not future.cancelled() and future.exception() is None:
            counts = tuple(future.result())
            self._post(lambda: setattr(self.data(tab), 'counts', counts))

    def mode(self, tab: Tab) -> str | None:
        return self.data(tab).mode or None

    def toggle_mode(self, nav: NavState, tab: Tab, how: str, to: str | None) -> None:
        """e, :echo, :pub: switch between Echo and Publish; the message stays."""
        if nav.layer == EDIT:
            nav.commit_edit(how)
        data = self.data(tab)
        data.mode = to or ('publish' if data.mode == 'echo' else 'echo')
        nav.layer = IN
        nav.log_line(how, f'now in {data.mode}')

    def publishers(self, nav: NavState, tab: Tab) -> int:
        counts = self.data(tab).counts
        if counts is not None:
            return counts[0]
        item = nav.item(tab)
        return item.publishers if item else 0

    # ---------- the rate ----------
    def rate(self, tab: Tab) -> float:
        """The repeat rate: the user's, else the publisher's as measured, else the default."""
        data = self.data(tab)
        if data.rate is not None:
            return data.rate
        if data.measured:
            return min(PUBLISH_RATE_MAX_HZ, max(PUBLISH_RATE_MIN_HZ, round(data.measured, 1)))
        return PUBLISH_DEFAULT_RATE_HZ

    def rate_note(self, tab: Tab) -> str:
        data = self.data(tab)
        if data.rate is not None:
            return 'your rate'
        return 'matches the publisher' if data.measured else 'default'

    def label_vars(self, tab: Tab | None) -> dict[str, Any]:
        if tab is None:
            return super().label_vars(tab)
        return {'rate': rate_text(self.rate(tab))}

    def _apply_rate(self, tab: Tab, rate: float | None) -> str:
        """Set the user's rate (None: back to the default one) and restart a running repeat at it.
        Returns the activity line of a restarted repeat, or ''."""
        data = self.data(tab)
        data.rate = rate
        repeat = data.repeat
        if repeat is None or repeat.rate == self.rate(tab):
            return ''
        now = self._bridge.now()
        repeat.sent_before, repeat.since, repeat.rate = repeat.sent(now), now, self.rate(tab)
        self._bridge.start_periodic_publish(tab.name, data.type, repeat.message, repeat.rate, repeat.time_setters)
        return f'↻ rate now {rate_text(repeat.rate)} Hz'

    def _set_rate(self, tab: Tab, rate: float) -> tuple[UndoEntry | None, str]:
        """A new rate: (its undo step, None when it didn't change; the activity line)."""
        if rate == self.rate(tab):
            return None, ''
        undo = UndoEntry(tab.key, RATE, self.data(tab).rate)
        return undo, self._apply_rate(tab, rate)

    def edit_rate(self, nav: NavState, tab: Tab, how: str) -> None:
        """R: type a new rate in place of the shown one (from Echo, switch to Publish first)."""
        if self.mode(tab) != 'publish':
            self.data(tab).mode = 'publish'
            nav.layer = IN
        text = rate_text(self.rate(tab))
        nav.editing = Editing(RATE, 0, text, old=text, fresh=True, field='repeat rate',
                              note='(type a number, enter keeps it)', crumb=('repeat rate',), back=nav.layer)
        nav.layer = EDIT
        nav.log_line(how, 'editing the repeat rate: type a number, enter keeps it')

    def command_rate(self, nav: NavState, tab: Tab, how: str, text: str) -> None:
        """:rate 5"""
        try:
            rate = parse_rate(text)
        except ValueError as error:
            nav.report_error(tab, str(error))
            nav.show_toast(f'{error} — usage: :rate 5', 'bad')
            nav.log_line(how, 'rate not changed')
            return
        undo, activity = self._set_rate(tab, rate)
        if undo:
            nav.push_undo(undo)
        if activity:
            nav.add_activity(tab, activity, 'g')
        nav.errlines.pop(tab.key, None)
        nav.show_toast(f'repeat rate {rate_text(rate)} Hz', 'info')
        nav.log_line(how, f'repeat rate on {tab.name} is {rate_text(rate)} Hz' + (' (u undoes)' if undo else ''))

    # ---------- rows ----------
    def echo_rows(self, nav: NavState, tab: Tab) -> list[Row]:
        """LATEST MESSAGE: one row per field, with the values it shows: the newest message, or the
        one it froze on (None before the first message)."""
        data = self.data(tab)
        if data.editor is None:
            return []
        received = self.received(nav, tab)
        return flat_rows(data.editor.fields, received.display if received else None)

    def received(self, nav: NavState, tab: Tab) -> Received | None:
        """The message LATEST MESSAGE shows: the one it froze on while frozen, else the newest."""
        data = self.data(tab)
        return data.shown if self.frozen(nav, tab) else data.latest

    def row_count(self, tab: Tab, area: Area) -> int:
        if area.id == ECHO:
            data = self.data(tab)
            return len(flat_rows(data.editor.fields, None)) if data.editor else 0
        return super().row_count(tab, area)

    def activate_row(self, nav: NavState, tab: Tab, area: Area, row: int, how: str) -> bool:
        """enter on an echoed field hides or shows it."""
        if area.id != ECHO:
            return super().activate_row(nav, tab, area, row, how)
        rows = self.echo_rows(nav, tab)
        if not 0 <= row < len(rows):
            return False
        hidden, name = self.data(tab).hidden, rows[row].field
        hidden.symmetric_difference_update({name})
        nav.log_line(how, f'{"hid" if name in hidden else "showing"} {name}')
        return True

    # ---------- echo: live and frozen ----------
    def frozen(self, nav: NavState, tab: Tab) -> bool:
        """An echo is frozen while the cursor is inside its LATEST MESSAGE."""
        area = nav.area()
        inside = nav.layer in (AREA, EDIT) and area is not None and area.id == ECHO
        return inside and nav.tab == tab and self.mode(tab) == 'echo' and self.data(tab).echo is not None

    def leave_area(self, tab: Tab, area: Area) -> str | None:
        if area.id == ECHO and self.data(tab).echo is not None:
            return 'out of the latest message: values are live again'
        return None

    def esc_label(self, tab: Tab, area: Area) -> str | None:
        return 'go live' if area.id == ECHO and self.data(tab).echo is not None else None

    def tick(self, nav: NavState) -> bool:
        """Drain every running echo: keep the newest message (converted once), count, rate, drops; a
        frozen echo only counts what arrived. True when the active tab shows something new: its
        echo's count or rate, or its repeat's sent count. An echo or repeat in another tab changes
        nothing on screen (its markers only change on start and stop), so it doesn't redraw."""
        changed = False
        now = self._bridge.now()
        for key, data in self._data.items():
            tab, echo = Tab.of(key), data.echo
            if echo is not None:
                messages, received, dropped, hz = echo.buffer.drain()
                fresh = received - echo.received
                echo.received, echo.dropped, echo.hz = received, dropped, hz
                if hz > 0:
                    data.measured = hz
                if messages:
                    data.latest = Received(messages[-1], message_to_display(messages[-1]))
                if self.frozen(nav, tab):
                    data.new_since += fresh
                else:
                    data.shown, data.new_since = data.latest, 0
            seen = ((echo.received, f'{echo.hz:.1f}', echo.dropped) if echo else None,
                    data.repeat.sent(now) if data.repeat else None)
            changed = changed or (tab == nav.tab and seen != data.seen)
            data.seen = seen
        return changed

    def toggle_echo(self, nav: NavState, tab: Tab, how: str) -> None:
        """space in Echo: start the echo, or stop it."""
        data = self.data(tab)
        if data.echo is not None:
            self._bridge.unsubscribe(tab.name)
            data.echo, data.latest, data.shown, data.new_since = None, None, None, 0
            nav.add_activity(tab, '■ echo stopped', 'dim')
            nav.log_line(how, 'stopped echo')
            return
        if not data.type:
            nav.show_toast(f'no type information for {tab.name}', 'bad')
            nav.log_line(how, 'nothing to echo')
            return
        data.echo = Echo(EchoBuffer(clock=self._bridge.now))
        future = self._bridge.subscribe(tab.name, data.type, data.echo.buffer)
        future.add_done_callback(lambda done: self._failed(nav, tab, done, 'echo', self._echo_failed))
        nav.add_activity(tab, '◉ echo started', 'c')
        nav.log_line(how, 'started echo')

    def _echo_failed(self, tab: Tab) -> None:
        self.data(tab).echo = None

    def yank_echo(self, nav: NavState, tab: Tab, how: str) -> None:
        """y in Echo: copy the message LATEST MESSAGE shows (the frozen one while frozen), exactly."""
        data, received = self.data(tab), self.received(nav, tab)
        if data.echo is None:
            problem = 'start the echo first (space)'
        elif received is None:
            problem = (f'no messages to copy: nobody publishes {tab.name}' if self.publishers(nav, tab) == 0
                       else f'no messages to copy yet: waiting for the first one on {tab.name}')
        else:
            problem = ''
        if problem:
            nav.show_toast(problem, 'bad')
            nav.log_line(how, 'nothing to copy yet')
            return
        nav.register = Register.of(data.type, 'message', tab.name, message_to_plain(received.message))
        which = 'frozen' if self.frozen(nav, tab) else 'latest'
        nav.show_toast(f'copied the {which} {nav.register.label} from {tab.name}', 'info')
        nav.log_line(how, f'copied the {which} message — p pastes it into an editor of the same type')

    # ---------- publish ----------
    def publish(self, nav: NavState, tab: Tab, how: str) -> None:
        """space in Publish: check the message, then publish it once."""
        built = self.checked(nav, tab, how)
        if built is None:
            return
        message, time_setters = built
        sent = summary(self.remember(tab), SUMMARY_MAX_CHARS)
        nav.errlines.pop(tab.key, None)
        future = self._bridge.publish_once(tab.name, self.data(tab).type, message, tuple(time_setters))
        future.add_done_callback(lambda done: self._failed(nav, tab, done, 'publish'))
        nav.flash_send(tab)
        nav.add_activity(tab, f'✓ published · {sent}' if sent else '✓ published', 'g')
        nav.log_line(how, f'published once on {tab.name}')

    def start_repeat(self, nav: NavState, tab: Tab, how: str) -> None:
        """r: publish the message at the rate until s stops it."""
        data = self.data(tab)
        if self.mode(tab) != 'publish':
            nav.log_line(how, 'r repeats a publish — e switches to Publish')
            return
        if data.repeat is not None:
            nav.show_toast(f'already repeating at {rate_text(data.repeat.rate)} Hz — s stops it', 'info')
            nav.log_line(how, 'already repeating')
            return
        built = self.checked(nav, tab, how)
        if built is None:
            return
        message, time_setters = built
        self.remember(tab)
        nav.errlines.pop(tab.key, None)
        rate = self.rate(tab)
        data.repeat = Repeat(message, tuple(time_setters), rate, self._bridge.now())
        future = self._bridge.start_periodic_publish(tab.name, data.type, message, rate, tuple(time_setters))
        future.add_done_callback(lambda done: self._failed(nav, tab, done, 'repeat', self._repeat_failed))
        nav.add_activity(tab, f'↻ repeating at {rate_text(rate)} Hz', 'g')
        nav.log_line(how, f'repeating at {rate_text(rate)} Hz')

    def _repeat_failed(self, tab: Tab) -> None:
        self.data(tab).repeat = None

    def stop(self, nav: NavState, tab: Tab, how: str) -> None:
        """s: stop the repeat. It never sends."""
        data = self.data(tab)
        if self.mode(tab) == 'echo':
            nav.log_line(how, 'space stops the echo; going into the latest message freezes it')
            return
        if data.repeat is None:
            nav.log_line(how, 'nothing running here')
            return
        self._bridge.stop_periodic_publish(tab.name)
        sent = data.repeat.sent(self._bridge.now())
        data.repeat = None
        nav.add_activity(tab, f'■ repeat stopped after {sent} sent', 'dim')
        nav.log_line(how, 'stopped repeating')

    def _failed(self, nav: NavState, tab: Tab, future: Any, what: str, undo=None) -> None:
        """On the bridge's thread: a subscribe or publish that failed says so (and undoes its state)."""
        error = None if future.cancelled() else future.exception()
        if error is None:
            return

        def report():
            if undo is not None:
                undo(tab)
            nav.add_activity(tab, f'✗ {what} failed: {error}', 'r')
        self._post(report)

    # ---------- running ----------
    def running(self) -> dict[Tab, tuple[Running, ...]]:
        markers = {}
        for key, data in self._data.items():
            tab = Tab.of(key)
            found = ((ECHOING,) if data.echo else ()) + (
                (Running('↻', f'{rate_text(data.repeat.rate)} Hz', 'ok'),) if data.repeat else ())
            if found:
                markers[tab] = found
        return markers

    # ---------- editing the rate ----------
    def commit_edit(self, tab: Tab, editing: Editing) -> Commit:
        if editing.area != RATE:
            return super().commit_edit(tab, editing)
        try:
            rate = parse_rate(editing.value)
        except ValueError as error:
            return Commit(False, str(error))
        running = self.data(tab).repeat is not None
        undo, activity = self._set_rate(tab, rate)
        text = f'repeat rate {rate_text(rate)} Hz' + (' (applied to the running repeat)' if running else '')
        return Commit(True, text + (' (u undoes)' if undo else ''), undo, (activity, 'g') if activity else ())

    def undo(self, nav: NavState, entry: UndoEntry) -> str:
        if entry.kind != RATE:
            return super().undo(nav, entry)
        tab = Tab.of(entry.owner)
        activity = self._apply_rate(tab, entry.data)
        if activity:
            nav.add_activity(tab, activity, 'g')
        return f'repeat rate on {tab.name} back to {rate_text(self.rate(tab))} Hz'

    # ---------- verbs ----------
    def verb(self, nav: NavState, tab: Tab | None, name: str, how: str, arg: Any = None) -> bool:
        if name == 'primary':
            (self.toggle_echo if self.mode(tab) == 'echo' else self.publish)(nav, tab, how)
        elif name == 'secondary':
            self.stop(nav, tab, how)
        elif name == 'toggle_mode':
            self.toggle_mode(nav, tab, how, arg)
        elif name == 'repeat':
            self.start_repeat(nav, tab, how)
        elif name == 'rate':
            self.edit_rate(nav, tab, how)
        elif name == 'set_rate':
            self.command_rate(nav, tab, how, arg or '')
        elif name in ('history_older', 'history_newer') and self.mode(tab) == 'echo':
            nav.log_line(how, 'the history is for Publish — e switches to it')
        elif name == 'yank' and self.mode(tab) == 'echo':
            self.yank_echo(nav, tab, how)
        elif name == 'paste' and self.mode(tab) == 'echo' and nav.register is not None:
            nav.show_toast('switch to Publish (e) to paste', 'bad')
            nav.log_line(how, 'no editor in Echo')
        else:
            return super().verb(nav, tab, name, how, arg)
        return True
