#!/usr/bin/env python3
# Copyright 2026 Jonas Vervoort
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

"""Time wizard — fill a builtin_interfaces/Time value several ways.

The pure conversions between a Time value (``{'sec', 'nanosec'}``) and the ways the wizard lets
you enter one never read the wall clock (the popup passes ``time.time()`` in), so they stay
deterministic and unit-testable without a running app.
"""

import time
from datetime import datetime
from typing import Any, Iterable

from textual import on
from textual.widget import Widget
from textual.widgets import Static

from ros_tui.ui.wizards.base import WizardScreen
from ros_tui.ui.wizards.components import ModeForm
from ros_tui.ui.wizards.registry import register

_WALLCLOCK_FORMAT = '%Y-%m-%d %H:%M:%S'  # Local time; the time wizard's wall-clock mode.


def seconds_str_to_stamp(text: str) -> dict[str, int]:
    """Parse a non-negative decimal-seconds string into ``{'sec', 'nanosec'}``.

    Splits on ``.`` so precision survives float rounding: ``'2.5'`` -> ``{'sec': 2, 'nanosec':
    500000000}``. The fractional part is padded/truncated to 9 digits. Raises ``ValueError`` on
    a negative value or non-numeric text.
    """
    text = text.strip()
    if text.startswith('-'):
        raise ValueError('time must not be negative')
    whole, dot, frac = text.partition('.')
    whole = whole or '0'
    if not whole.isdigit() or (dot and frac and not frac.isdigit()):
        raise ValueError('not a number')
    nanosec = int((frac + '000000000')[:9]) if frac else 0
    return {'sec': int(whole), 'nanosec': nanosec}


def epoch_to_stamp(epoch: float) -> dict[str, int]:
    """Convert a POSIX epoch (float seconds) into ``{'sec', 'nanosec'}``, clamped at zero."""
    epoch = max(epoch, 0.0)
    sec = int(epoch)
    nanosec = int(round((epoch - sec) * 1_000_000_000))
    if nanosec >= 1_000_000_000:  # rounding can carry into the next second.
        sec += 1
        nanosec -= 1_000_000_000
    return {'sec': sec, 'nanosec': nanosec}


def parse_wallclock(text: str) -> float:
    """Parse a local ``YYYY-MM-DD HH:MM:SS`` string into a POSIX epoch (float seconds)."""
    return datetime.strptime(text.strip(), _WALLCLOCK_FORMAT).timestamp()


def stamp_to_seconds_str(stamp: dict[str, int]) -> str:
    """Render ``{'sec', 'nanosec'}`` as a trimmed decimal-seconds string (inverse of parse)."""
    sec = int(stamp.get('sec', 0))
    nanosec = int(stamp.get('nanosec', 0))
    if nanosec == 0:
        return str(sec)
    return f'{sec}.{nanosec:09d}'.rstrip('0')


def _parse_time(value: Any) -> tuple[str, str]:
    """Best-effort (mode, seconds_str) prefill from a parsed time field value."""
    if isinstance(value, dict) and ('sec' in value or 'nanosec' in value):
        return 'seconds', stamp_to_seconds_str(value)
    return 'now', '0.0'


@register('builtin_interfaces/Time')
class TimeWizardPopup(WizardScreen):
    """Fill a builtin_interfaces/Time value. Dismisses with the value, or None if cancelled.

    Every mode is just an input method; the dismissed value is either the ``'now'`` magic string
    (stamped at send time) or a concrete ``{'sec', 'nanosec'}`` dict. The wall-clock and relative
    modes resolve against the *system* clock at Apply time (not ROS sim-time).
    """

    TITLE = 'Time — choose how to enter the stamp'
    PREFIX = 'time-wizard'

    def __init__(self, current_value: Any = None):
        super().__init__()
        self._mode, seconds = _parse_time(current_value)
        self._modes = [
            ('now', 'now — stamped at send time', ()),
            ('seconds', 'seconds — decimal seconds since epoch',
             (('time-seconds', 'seconds', seconds, 'e.g. 2.5'),)),
            ('wallclock', 'wall-clock — local date & time',
             # Prefill the wall-clock field with the current local time so it's editable, not blank.
             (('time-wallclock', 'date/time', datetime.now().strftime(_WALLCLOCK_FORMAT),
               'YYYY-MM-DD HH:MM:SS'),)),
            ('relative', 'relative — offset from now (seconds)',
             (('time-offset', 'offset s', '0.0', 'e.g. -5 or 10'),)),
        ]

    def compose_body(self) -> Iterable[Widget]:
        yield ModeForm(self._modes, radio_id='time-wizard-mode', initial=self._mode)
        yield Static('', id='time-wizard-result', classes='wizard-result')

    def on_mount(self) -> None:
        self._refresh_result()

    @property
    def _form(self) -> ModeForm:
        return self.query_one(ModeForm)

    @on(ModeForm.Changed)
    def _on_form_changed(self, event: ModeForm.Changed) -> None:
        event.stop()
        self._set_error('')
        self._refresh_result()

    def _refresh_result(self) -> None:
        value = self._compute(strict=False)
        result = self.query_one('#time-wizard-result', Static)
        if value == 'now':
            result.update('= now (stamped at send)')
        elif value is None:
            result.update('= (enter a valid value)')
        else:
            result.update(f"= sec: {value['sec']}  nanosec: {value['nanosec']}")

    def _compute(self, strict: bool) -> Any:
        mode = self._form.current_mode
        if mode == 'now':
            return 'now'
        if mode == 'seconds':
            try:
                return seconds_str_to_stamp(self._form.raw('time-seconds'))
            except ValueError:
                if strict:
                    self._set_error('enter non-negative seconds, e.g. 2.5')
                return None
        if mode == 'wallclock':
            try:
                return epoch_to_stamp(parse_wallclock(self._form.raw('time-wallclock')))
            except ValueError:
                if strict:
                    self._set_error('use YYYY-MM-DD HH:MM:SS')
                return None
        try:  # relative
            offset = float(self._form.raw('time-offset'))
        except ValueError:
            if strict:
                self._set_error('offset must be a number of seconds')
            return None
        return epoch_to_stamp(time.time() + offset)

    def build_value(self) -> Any:
        return self._compute(strict=True)
