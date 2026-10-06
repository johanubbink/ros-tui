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

"""Header wizard — fill a std_msgs/Header, opening the Time wizard for its stamp."""

from typing import Any, Iterable

from textual import on
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from ros_tui.ui.helpers.header import parse_header as _parse_header
from ros_tui.ui.wizards.base import WizardScreen
from ros_tui.ui.wizards.components import pressed_key
from ros_tui.ui.wizards.registry import register
from ros_tui.ui.wizards.time import (
    TimeWizardPopup,
    seconds_str_to_stamp,
    stamp_to_seconds_str,
)

# This wizard doesn't use ModeForm: its frame_id row spans two modes and its stamp row carries
# a Fill button + a nested Time sub-wizard, which don't fit ModeForm's one-group-per-mode shape.


@register('std_msgs/Header')
class HeaderWizardPopup(WizardScreen):
    """Fill a std_msgs/Header field. Dismisses with the field value, or None if cancelled.

    Dismiss values round-trip through ``build_message``:
      auto   -> 'auto'                                        (empty header, stamped at send)
      now    -> {'stamp': 'now', 'frame_id': <id>}           (stamped at send)
      manual -> {'stamp': {'sec': s, 'nanosec': n}, 'frame_id': <id>}
    """

    TITLE = 'Header — how should the stamp be filled?'
    PREFIX = 'header-wizard'

    DEFAULT_CSS = """
    #header-wizard-box .field-row Static { width: 20; }
    HeaderWizardPopup #header-wizard-stamp-fill { width: auto; margin-left: 1; }
    """

    _MODES = ('auto', 'now', 'manual')

    def __init__(self, current_value: Any = 'auto'):
        super().__init__()
        self._mode, self._frame_id, stamp = _parse_header(current_value)
        # Keep an editable stamp internally; the nested Time wizard may set it to 'now'.
        self._stamp_value: Any = stamp if isinstance(stamp, dict) else {'sec': 0, 'nanosec': 0}

    def compose_body(self) -> Iterable[Widget]:
        with RadioSet(id='header-wizard-mode'):
            yield RadioButton('auto — empty header, stamped at send', value=self._mode == 'auto')
            yield RadioButton('now — stamped at send, with frame_id', value=self._mode == 'now')
            yield RadioButton('manual — set stamp and frame_id', value=self._mode == 'manual')
        with Horizontal(classes='field-row', id='header-wizard-frame-row'):
            yield Static('frame_id')
            yield Input(value=self._frame_id, id='header-wizard-frame')
        with Horizontal(classes='field-row', id='header-wizard-stamp-row'):
            yield Static('stamp [sec. (dec)]', id='header-wizard-stamp-label')
            yield Input(value=self._stamp_text(), id='header-wizard-stamp')
            yield Button('Fill', id='header-wizard-stamp-fill')

    def on_mount(self) -> None:
        self._refresh_visibility()

    @on(RadioSet.Changed, '#header-wizard-mode')
    def _on_mode_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._refresh_visibility()

    def _current_mode(self) -> str:
        return pressed_key(self.query_one('#header-wizard-mode', RadioSet), self._MODES)

    def _refresh_visibility(self) -> None:
        mode = self._current_mode()
        self.query_one('#header-wizard-frame-row').display = mode in ('now', 'manual')
        self.query_one('#header-wizard-stamp-row').display = mode == 'manual'

    def _stamp_text(self) -> str:
        """Initial text for the stamp input: 'now' or trimmed decimal seconds."""
        return 'now' if self._stamp_value == 'now' else stamp_to_seconds_str(self._stamp_value)

    def _stamp_from_input(self) -> Any:
        """Parse the stamp input as 'now' or a {sec, nanosec} dict; None if it can't be parsed."""
        text = self.query_one('#header-wizard-stamp', Input).value.strip()
        if text == 'now':
            return 'now'
        try:
            return seconds_str_to_stamp(text)
        except ValueError:
            return None

    def wizard_action(self) -> None:
        """ctrl+w opens the Time fill assist when the stamp input is focused (like the editor)."""
        if self._current_mode() == 'manual' and (
            self.app.focused is self.query_one('#header-wizard-stamp', Input)
        ):
            self._open_time_wizard()

    @on(Button.Pressed, '#header-wizard-stamp-fill')
    def _fill_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._open_time_wizard()

    def _open_time_wizard(self) -> None:
        self.app.push_screen(TimeWizardPopup(self._stamp_from_input()), self._on_time_picked)

    def _on_time_picked(self, value: Any) -> None:
        if value is None:
            return
        text = 'now' if value == 'now' else stamp_to_seconds_str(value)
        self.query_one('#header-wizard-stamp', Input).value = text

    def build_value(self) -> Any:
        mode = self._current_mode()
        if mode == 'auto':
            return 'auto'
        frame_id = self.query_one('#header-wizard-frame', Input).value
        if mode == 'now':
            return {'stamp': 'now', 'frame_id': frame_id}
        stamp = self._stamp_from_input()
        if stamp is None:
            self._set_error('stamp: enter seconds (e.g. 2.5) or "now" — or use Fill')
            return None
        return {'stamp': stamp, 'frame_id': frame_id}
