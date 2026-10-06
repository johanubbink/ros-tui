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

The pure conversions between a Time value and the ways to enter one live in
ros_tui.ui.helpers.time, shared with the new UI's Time and Header helpers.
"""

import time
from datetime import datetime
from typing import Any, Iterable

from textual import on
from textual.widget import Widget
from textual.widgets import Static

from ros_tui.ui.helpers.time import WALLCLOCK_FORMAT as _WALLCLOCK_FORMAT
from ros_tui.ui.helpers.time import stamp_to_seconds_str  # noqa: F401 - re-exported for header.py and __init__
from ros_tui.ui.helpers.time import epoch_to_stamp, parse_wallclock, seconds_str_to_stamp
from ros_tui.ui.helpers.time import parse_time as _parse_time
from ros_tui.ui.wizards.base import WizardScreen
from ros_tui.ui.wizards.components import ModeForm
from ros_tui.ui.wizards.registry import register


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
