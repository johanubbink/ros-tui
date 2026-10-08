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

"""What the UI tells you about what happened: the key log, the toast, the errline under an entry's
panel, the activity lines and the primary button's send flash. Each times out on its own clock.

Pure Python. NavState and the entries write to it through `NavState.feedback`; the views read it.
Time comes only from `clock` (the bridge's `now()` in the app, FakeBridge's ManualClock in tests),
and the time of day an activity line shows from `wall` (the bridge's `time_of_day()`), so both are
repeatable in tests. `tick()` expires what is timed.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, NamedTuple

from ros_tui.constants import (NAV_ACTIVITY_FRESH_S, NAV_ACTIVITY_MAX, NAV_ERRLINE_S, NAV_FLASH_S, NAV_LOG_LINES,
                               NAV_TOAST_S)


@dataclass(frozen=True)
class Toast:
    text: str
    kind: str = ''  # '', 'ok', 'info' or 'bad'.
    until: float = 0.0  # Clock time it goes away at.


class Errline(NamedTuple):
    text: str  # A bad value's message, shown under the entry's panel.
    until: float  # Clock time it goes away at.


@dataclass(frozen=True)
class ActivityLine:
    kind: str  # The entry's kind ('' for none) and name, so :log can jump there.
    name: str
    text: str
    cls: str = ''  # Its colour: g ok, r bad, c live, y warn, dim.
    time: str = ''  # The time of day it happened, as shown: '09:41:03'.
    at: float = 0.0  # Feedback.clock() when it happened, for the fresh highlight.


def clock_text(seconds: float) -> str:
    """A time of day in seconds since midnight as 'HH:MM:SS'."""
    whole = int(seconds) % 86400
    return f'{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}'


@dataclass
class Feedback:
    clock: Callable[[], float] = lambda: 0.0  # Seconds; the app passes the bridge's now().
    wall: Callable[[], float] = lambda: 0.0  # The time of day in seconds; the app passes the bridge's time_of_day().
    log: list[tuple[str, str]] = field(default_factory=list)  # (key, what happened), newest first.
    toast: Toast | None = None
    activity: list[ActivityLine] = field(default_factory=list)  # Newest first.
    _errlines: dict[Any, Errline] = field(default_factory=dict)  # By entry tab: its current error line.
    flash: tuple[Any, float] | None = None  # (entry tab, clock time it ends) of the primary button's send flash.
    _fresh_shown: int = 0  # How many activity lines were fresh at the last tick, so it redraws when one fades.

    def log_line(self, how: str, what: str) -> None:
        self.log.insert(0, (how, what))
        del self.log[NAV_LOG_LINES:]

    def hint(self, how: str) -> None:
        self.log_line(how, f'nothing on "{how}" here — ? shows the keys')

    def show_toast(self, text: str, kind: str = '') -> None:
        self.toast = Toast(text, kind, self.clock() + NAV_TOAST_S)

    def refuse(self, how: str, toast: str, log: str | None = None) -> None:
        """A key that can't do its thing here: a red toast saying why, and the log line (`log`, else
        the toast's text)."""
        self.show_toast(toast, 'bad')
        self.log_line(how, toast if log is None else log)

    def errline(self, tab: Any) -> str:
        line = self._errlines.get(tab)
        return line.text if line else ''

    def report_error(self, tab: Any, message: str) -> None:
        """A bad value or a blocked send: an errline under the entry's panel and a red activity line."""
        self._errlines[tab] = Errline(message, self.clock() + NAV_ERRLINE_S)
        self.add_activity(tab, f'✗ {message}', 'r')

    def clear_error(self, tab: Any) -> None:
        """The entry's errline goes: what it was about is fixed, or over."""
        self._errlines.pop(tab, None)

    def add_activity(self, tab: Any, text: str, cls: str = '') -> None:
        """A line in the activity strip and :log, about the entry of `tab` (a Tab, or None)."""
        self.activity.insert(0, ActivityLine(tab.kind if tab else '', tab.name if tab else '', text, cls,
                                             clock_text(self.wall()), self.clock()))
        del self.activity[NAV_ACTIVITY_MAX:]

    def fresh_lines(self) -> int:
        """How many of the newest activity lines are fresh (highlighted for NAV_ACTIVITY_FRESH_S)."""
        now = self.clock()
        return next((i for i, line in enumerate(self.activity) if now - line.at >= NAV_ACTIVITY_FRESH_S),
                    len(self.activity))

    def is_fresh(self, line: ActivityLine) -> bool:
        return self.clock() - line.at < NAV_ACTIVITY_FRESH_S

    def flash_send(self, tab: Any) -> None:
        """Something went out on space / ^s: the entry's primary button flashes for NAV_FLASH_S."""
        self.flash = (tab, self.clock() + NAV_FLASH_S)

    def flashing(self, tab: Any) -> bool:
        return self.flash is not None and self.flash[0] == tab and self.clock() < self.flash[1]

    def tick(self) -> bool:
        """Expire what is timed (the toast, errlines, the send flash, the highlight of fresh activity
        lines). True when something on screen changed."""
        now = self.clock()
        expired = [key for key, line in self._errlines.items() if now >= line.until]
        for key in expired:
            del self._errlines[key]
        changed = bool(expired)
        if self.toast and now >= self.toast.until:
            self.toast = None
            changed = True
        if self.flash and now >= self.flash[1]:
            self.flash = None
            changed = True
        # A new line is drawn by whatever added it; only its highlight fading needs a redraw.
        fresh = self.fresh_lines()
        faded, self._fresh_shown = fresh < self._fresh_shown, fresh
        return changed or faded
