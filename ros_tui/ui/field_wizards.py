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
Context-aware "wizard" popups that fill a message field's YAML for the user.

A single wizard button / ``ctrl+w`` on the Topics tab inspects the field on the editor's
cursor line and, if that field's type has a registered wizard, opens it. The wizard dismisses
with the field's *value* (plain dict/scalar); the tab renders it back into the editor block.
The pure text helpers below (cursor path, block range, block render/replace) hold no textual
dependency so they can be unit-tested without a running app.
"""

import math
import time
from datetime import datetime
from typing import Any

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from ros_tui.ros.message_yaml import _dump_yaml

_WALLCLOCK_FORMAT = '%Y-%m-%d %H:%M:%S'  # Local time; the time wizard's wall-clock mode.


# --------------------------------------------------------------------------- pure text helpers


def cursor_field_path(text: str, row: int) -> list[str]:
    """Dotted key path (as a list) of the YAML field enclosing ``row``.

    An indentation-stack walk: each mapping key opens a level; a line at the same or lower
    indent closes its siblings/ancestors first. List items and comments carry no key.
    """
    lines = text.splitlines()
    if not lines:
        return []
    row = max(0, min(row, len(lines) - 1))
    stack: list[tuple[int, str]] = []  # (indent, key)
    for line in lines[: row + 1]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('- '):
            continue
        separator = line.find(':')
        if separator == -1:
            continue
        key = line[:separator].strip()
        if not key:
            continue
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
    return [key for _, key in stack]


def field_type_at(structure: Any, path: list[str]) -> str | None:
    """Type label of the field at ``path`` in a ``FieldNode`` tuple, or None if absent."""
    nodes = structure
    node = None
    for name in path:
        node = next((candidate for candidate in nodes if candidate.name == name), None)
        if node is None:
            return None
        nodes = node.children
    return node.type_label if node is not None else None


def matched_wizard(structure: Any, path: list[str]) -> tuple[list[str], type] | None:
    """Outermost prefix of ``path`` whose field type has a registered wizard, with the class."""
    for depth in range(1, len(path) + 1):
        prefix = path[:depth]
        type_label = field_type_at(structure, prefix)
        if type_label in WIZARDS:
            return prefix, WIZARDS[type_label]
    return None


def field_block_range(text: str, path: list[str]) -> tuple[int, int, int] | None:
    """Line span ``(start, end_exclusive, indent)`` of the field block at ``path``.

    The block runs from the field's ``key:`` line to the next line at the same or lower
    indent (a sibling/ancestor), stopping before a trailing comment block (e.g. the
    ``# constants:`` hint) or EOF. Trailing blank lines are excluded.
    """
    lines = text.splitlines()
    start = next((i for i in range(len(lines)) if cursor_field_path(text, i) == path), None)
    if start is None:
        return None
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        stripped = lines[end].strip()
        if not stripped:
            end += 1
            continue
        if stripped.startswith('#'):
            break
        if len(lines[end]) - len(lines[end].lstrip()) <= indent:
            break
        end += 1
    while end - 1 > start and not lines[end - 1].strip():
        end -= 1  # Don't swallow blank lines that separate the block from what follows.
    return start, end, indent


def render_field_block(field_name: str, value: Any, indent: int) -> str:
    """Render ``{field_name: value}`` as YAML, each line indented by ``indent`` spaces."""
    pad = ' ' * indent
    dumped = _dump_yaml({field_name: value}).rstrip('\n')
    return '\n'.join(pad + line if line else line for line in dumped.splitlines())


def replace_block(text: str, start: int, end_exclusive: int, new_block: str) -> tuple[str, int]:
    """Replace lines ``[start, end_exclusive)`` with ``new_block``; return (text, cursor_row)."""
    lines = text.splitlines()
    result = lines[:start] + new_block.splitlines() + lines[end_exclusive:]
    joined = '\n'.join(result)
    if text.endswith('\n'):
        joined += '\n'
    return joined, start


# --------------------------------------------------------------------------- header wizard


class HeaderWizardPopup(ModalScreen[object]):
    """Fill a std_msgs/Header field. Dismisses with the field value, or None if cancelled.

    Dismiss values round-trip through ``build_message``:
      auto   -> 'auto'                                        (empty header, stamped at send)
      now    -> {'stamp': 'now', 'frame_id': <id>}           (stamped at send)
      manual -> {'stamp': {'sec': s, 'nanosec': n}, 'frame_id': <id>}
    """

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel', priority=True),
    ]

    DEFAULT_CSS = """
    HeaderWizardPopup { align: center middle; }
    HeaderWizardPopup #header-wizard-box {
        width: 60; height: auto; border: round $primary; padding: 1 2;
    }
    HeaderWizardPopup Static { height: 1; }
    HeaderWizardPopup RadioSet { height: auto; margin-bottom: 1; }
    HeaderWizardPopup .field-row { height: 3; width: 1fr; }
    HeaderWizardPopup .field-row Static { width: 10; content-align: left middle; height: 3; }
    HeaderWizardPopup .field-row Input { width: 1fr; }
    HeaderWizardPopup #header-wizard-stamp-summary { width: 1fr; content-align: left middle; }
    HeaderWizardPopup #header-wizard-time-row { height: 3; }
    HeaderWizardPopup #header-wizard-error { color: $error; text-style: bold; }
    HeaderWizardPopup Button {
        margin-right: 1; background: $surface; color: $text; border: round $primary;
    }
    HeaderWizardPopup Button:focus {
        background: $primary; color: $text; border: round $primary; text-style: bold;
    }
    HeaderWizardPopup #header-wizard-buttons { height: 3; margin-top: 1; }
    """

    _MODES = ('auto', 'now', 'manual')

    def __init__(self, current_value: Any = 'auto'):
        super().__init__()
        self._mode, self._frame_id, stamp = _parse_header(current_value)
        # Keep an editable stamp internally; the nested Time wizard may set it to 'now'.
        self._stamp_value: Any = stamp if isinstance(stamp, dict) else {'sec': 0, 'nanosec': 0}

    def compose(self):
        with Vertical(id='header-wizard-box'):
            yield Static('Header — how should the stamp be filled?')
            with RadioSet(id='header-wizard-mode'):
                yield RadioButton('auto — empty header, stamped at send', value=self._mode == 'auto')
                yield RadioButton('now — stamped at send, with frame_id', value=self._mode == 'now')
                yield RadioButton('manual — set stamp and frame_id', value=self._mode == 'manual')
            with Horizontal(classes='field-row', id='header-wizard-frame-row'):
                yield Static('frame_id')
                yield Input(value=self._frame_id, id='header-wizard-frame')
            with Horizontal(classes='field-row', id='header-wizard-stamp-row'):
                yield Static('stamp')
                yield Static(self._stamp_summary(), id='header-wizard-stamp-summary')
            with Horizontal(id='header-wizard-time-row'):
                yield Button('Set time… (ctrl+w)', id='header-wizard-set-time')
            yield Static('', id='header-wizard-error')
            with Horizontal(id='header-wizard-buttons'):
                yield Button('Apply', id='header-wizard-apply')
                yield Button('Cancel', id='header-wizard-cancel')

    def on_mount(self) -> None:
        self._refresh_visibility()

    @on(RadioSet.Changed, '#header-wizard-mode')
    def _on_mode_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._refresh_visibility()

    def _current_mode(self) -> str:
        index = self.query_one('#header-wizard-mode', RadioSet).pressed_index
        return self._MODES[index] if 0 <= index < len(self._MODES) else 'auto'

    def _refresh_visibility(self) -> None:
        mode = self._current_mode()
        self.query_one('#header-wizard-frame-row').display = mode in ('now', 'manual')
        self.query_one('#header-wizard-stamp-row').display = mode == 'manual'
        self.query_one('#header-wizard-time-row').display = mode == 'manual'

    def _stamp_summary(self) -> str:
        if self._stamp_value == 'now':
            return 'now (stamped at send)'
        return (
            f"{stamp_to_seconds_str(self._stamp_value)} s  "
            f"(sec {self._stamp_value['sec']}, nanosec {self._stamp_value['nanosec']})"
        )

    def wizard_action(self) -> None:
        """ctrl+w inside the header wizard opens the nested Time wizard (manual mode only)."""
        if self._current_mode() == 'manual':
            self._open_time_wizard()

    @on(Button.Pressed, '#header-wizard-set-time')
    def _set_time_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._open_time_wizard()

    def _open_time_wizard(self) -> None:
        self.app.push_screen(TimeWizardPopup(self._stamp_value), self._on_time_picked)

    def _on_time_picked(self, value: Any) -> None:
        if value is None:
            return
        self._stamp_value = value
        self.query_one('#header-wizard-stamp-summary', Static).update(self._stamp_summary())

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, '#header-wizard-cancel')
    def _cancel_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    @on(Button.Pressed, '#header-wizard-apply')
    def _apply_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        value = self._build_value()
        if value is not None:
            self.dismiss(value)

    def _build_value(self) -> Any:
        mode = self._current_mode()
        if mode == 'auto':
            return 'auto'
        frame_id = self.query_one('#header-wizard-frame', Input).value
        if mode == 'now':
            return {'stamp': 'now', 'frame_id': frame_id}
        return {'stamp': self._stamp_value, 'frame_id': frame_id}

    def _set_error(self, text: str) -> None:
        self.query_one('#header-wizard-error', Static).update(text)


def _parse_header(value: Any) -> tuple[str, str, Any]:
    """Best-effort (mode, frame_id, stamp) prefill from a parsed header field value.

    ``stamp`` is a ``{'sec', 'nanosec'}`` dict for a manual header, else ``None``.
    """
    if not isinstance(value, dict):
        return 'auto', '', None
    frame_id = str(value.get('frame_id', ''))
    stamp = value.get('stamp')
    if stamp == 'now':
        return 'now', frame_id, None
    if isinstance(stamp, dict):
        return 'manual', frame_id, {
            'sec': int(stamp.get('sec', 0)),
            'nanosec': int(stamp.get('nanosec', 0)),
        }
    return 'auto', frame_id, None


# --------------------------------------------------------------------------- quaternion math
#
# The rotation math is delegated to tf_transformations (the ROS wrapper over transforms3d) so
# the conventions match the rest of the ROS ecosystem. It is imported lazily inside each helper
# so this module still imports without a ROS environment (the pure-text helpers above, and the
# wizard registry, are unit-tested with no rclpy/tf present).


def quat_from_euler(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    """(x, y, z, w) from ROS RPY: roll=X, pitch=Y, yaw=Z, intrinsic ZYX ('sxyz'), radians."""
    from tf_transformations import quaternion_from_euler

    x, y, z, w = quaternion_from_euler(roll, pitch, yaw)  # default axes='sxyz'
    return float(x), float(y), float(z), float(w)


def quat_about_axis(ax: float, ay: float, az: float, angle: float) -> tuple[float, float, float, float]:
    """(x, y, z, w) for a rotation of ``angle`` rad about axis (ax, ay, az); zero axis -> identity."""
    if ax == 0.0 and ay == 0.0 and az == 0.0:
        return 0.0, 0.0, 0.0, 1.0
    from tf_transformations import quaternion_about_axis

    x, y, z, w = quaternion_about_axis(angle, (ax, ay, az))
    return float(x), float(y), float(z), float(w)


def normalize_quat(x: float, y: float, z: float, w: float) -> tuple[float, float, float, float]:
    """Scale (x, y, z, w) to unit length; a zero-length quaternion becomes the identity."""
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        return 0.0, 0.0, 0.0, 1.0
    return x / norm, y / norm, z / norm, w / norm


def clean_quat(x: float, y: float, z: float, w: float, ndigits: int = 6) -> dict[str, float]:
    """Round to ``ndigits`` and collapse ``-0.0`` to ``0.0`` so the dumped YAML stays tidy."""
    def clean(value: float) -> float:
        rounded = round(value, ndigits)
        return 0.0 if rounded == 0.0 else rounded

    return {'x': clean(x), 'y': clean(y), 'z': clean(z), 'w': clean(w)}


# --------------------------------------------------------------------------- quaternion wizard


class QuaternionWizardPopup(ModalScreen[object]):
    """Fill a geometry_msgs/Quaternion field. Dismisses with ``{x, y, z, w}`` or None if cancelled.

    Every mode is just an input method; the dismissed value is always the normalized quaternion.
    Angles use the shared degrees/radians toggle. Euler is ROS RPY (roll=X, pitch=Y, yaw=Z,
    intrinsic ZYX) — the same convention as tf's ``quaternion_from_euler``.
    """

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel', priority=True),
    ]

    DEFAULT_CSS = """
    QuaternionWizardPopup { align: center middle; }
    QuaternionWizardPopup #quat-wizard-box {
        width: 64; height: auto; border: round $primary; padding: 1 2;
    }
    QuaternionWizardPopup Static { height: 1; }
    QuaternionWizardPopup RadioSet { height: auto; margin-bottom: 1; }
    QuaternionWizardPopup .field-row { height: 3; width: 1fr; }
    QuaternionWizardPopup .field-row Static { width: 10; content-align: left middle; height: 3; }
    QuaternionWizardPopup .field-row Input { width: 1fr; }
    QuaternionWizardPopup #quat-wizard-result { color: $success; text-style: bold; margin-top: 1; }
    QuaternionWizardPopup #quat-wizard-error { color: $error; text-style: bold; }
    QuaternionWizardPopup #quat-wizard-buttons { height: 3; margin-top: 1; }
    QuaternionWizardPopup #quat-wizard-buttons Button {
        margin-right: 1; background: $surface; color: $text; border: round $primary;
    }
    QuaternionWizardPopup #quat-wizard-buttons Button:focus {
        background: $primary; color: $text; border: round $primary; text-style: bold;
    }
    """

    _MODES = ('quaternion', 'euler', 'yaw', 'axis_angle')
    _UNITS = ('degrees', 'radians')
    # Per-mode input rows: (field_id, label). Field ids are unique across modes.
    _LAYOUT = {
        'quaternion': (('quat-x', 'x'), ('quat-y', 'y'), ('quat-z', 'z'), ('quat-w', 'w')),
        'euler': (('euler-roll', 'roll'), ('euler-pitch', 'pitch'), ('euler-yaw', 'yaw')),
        'yaw': (('yaw-only', 'yaw'),),
        'axis_angle': (('axis-x', 'axis x'), ('axis-y', 'axis y'),
                       ('axis-z', 'axis z'), ('axis-angle', 'angle')),
    }

    def __init__(self, current_value: Any = None):
        super().__init__()
        self._mode = 'quaternion'
        self._unit = 'degrees'
        self._values = {
            **_parse_quaternion(current_value),
            'euler-roll': '0.0', 'euler-pitch': '0.0', 'euler-yaw': '0.0',
            'yaw-only': '0.0',
            'axis-x': '0.0', 'axis-y': '0.0', 'axis-z': '1.0', 'axis-angle': '0.0',
        }

    def compose(self):
        with Vertical(id='quat-wizard-box'):
            yield Static('Quaternion — choose how to enter the rotation')
            with RadioSet(id='quat-wizard-mode'):
                yield RadioButton('quaternion — raw x/y/z/w', value=self._mode == 'quaternion')
                yield RadioButton('euler RPY — roll(X)/pitch(Y)/yaw(Z), ROS intrinsic ZYX',
                                  value=self._mode == 'euler')
                yield RadioButton('yaw only — rotation about Z (planar)', value=self._mode == 'yaw')
                yield RadioButton('axis-angle — axis (x,y,z) + angle', value=self._mode == 'axis_angle')
            with RadioSet(id='quat-wizard-unit'):
                yield RadioButton('degrees', value=self._unit == 'degrees')
                yield RadioButton('radians', value=self._unit == 'radians')
            for mode, rows in self._LAYOUT.items():
                for field_id, label in rows:
                    with Horizontal(classes=f'field-row mode-{mode}', id=f'{field_id}-row'):
                        yield Static(label)
                        yield Input(value=self._values[field_id], id=field_id)
            yield Static('', id='quat-wizard-result')
            yield Static('', id='quat-wizard-error')
            with Horizontal(id='quat-wizard-buttons'):
                yield Button('Apply', id='quat-wizard-apply')
                yield Button('Cancel', id='quat-wizard-cancel')

    def on_mount(self) -> None:
        self._refresh_visibility()
        self._refresh_result()

    def _current_mode(self) -> str:
        index = self.query_one('#quat-wizard-mode', RadioSet).pressed_index
        return self._MODES[index] if 0 <= index < len(self._MODES) else 'quaternion'

    def _current_unit(self) -> str:
        index = self.query_one('#quat-wizard-unit', RadioSet).pressed_index
        return self._UNITS[index] if 0 <= index < len(self._UNITS) else 'degrees'

    def _refresh_visibility(self) -> None:
        mode = self._current_mode()
        for candidate in self._MODES:
            for row in self.query(f'.mode-{candidate}'):
                row.display = candidate == mode
        self.query_one('#quat-wizard-unit', RadioSet).display = mode != 'quaternion'

    @on(RadioSet.Changed)
    def _on_radio_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._refresh_visibility()
        self._set_error('')
        self._refresh_result()

    @on(Input.Changed)
    def _on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._set_error('')
        self._refresh_result()

    def _refresh_result(self) -> None:
        value = self._compute(strict=False)
        result = self.query_one('#quat-wizard-result', Static)
        if value is None:
            result.update('= (enter valid numbers)')
        else:
            result.update(f"= x: {value['x']}  y: {value['y']}  z: {value['z']}  w: {value['w']}")

    def _to_rad(self, value: float) -> float:
        return math.radians(value) if self._current_unit() == 'degrees' else value

    def _floats(self, field_ids: list[str], strict: bool) -> list[float] | None:
        values = []
        for field_id in field_ids:
            try:
                values.append(float(self.query_one(f'#{field_id}', Input).value))
            except ValueError:
                if strict:
                    self._set_error('all fields must be numbers')
                return None
        return values

    def _compute(self, strict: bool) -> dict[str, float] | None:
        mode = self._current_mode()
        if mode == 'quaternion':
            raw = self._floats(['quat-x', 'quat-y', 'quat-z', 'quat-w'], strict)
            if raw is None:
                return None
            x, y, z, w = normalize_quat(*raw)
        elif mode == 'euler':
            raw = self._floats(['euler-roll', 'euler-pitch', 'euler-yaw'], strict)
            if raw is None:
                return None
            x, y, z, w = quat_from_euler(*(self._to_rad(v) for v in raw))
        elif mode == 'yaw':
            raw = self._floats(['yaw-only'], strict)
            if raw is None:
                return None
            x, y, z, w = quat_from_euler(0.0, 0.0, self._to_rad(raw[0]))
        else:  # axis_angle
            raw = self._floats(['axis-x', 'axis-y', 'axis-z', 'axis-angle'], strict)
            if raw is None:
                return None
            x, y, z, w = quat_about_axis(raw[0], raw[1], raw[2], self._to_rad(raw[3]))
        return clean_quat(x, y, z, w)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, '#quat-wizard-cancel')
    def _cancel_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    @on(Button.Pressed, '#quat-wizard-apply')
    def _apply_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        value = self._compute(strict=True)
        if value is not None:
            self.dismiss(value)

    def _set_error(self, text: str) -> None:
        self.query_one('#quat-wizard-error', Static).update(text)


def _parse_quaternion(value: Any) -> dict[str, str]:
    """Best-effort x/y/z/w string prefill from a parsed quaternion field value (default identity)."""
    if not isinstance(value, dict):
        return {'quat-x': '0.0', 'quat-y': '0.0', 'quat-z': '0.0', 'quat-w': '1.0'}
    return {
        'quat-x': str(value.get('x', 0.0)),
        'quat-y': str(value.get('y', 0.0)),
        'quat-z': str(value.get('z', 0.0)),
        'quat-w': str(value.get('w', 1.0)),
    }


# --------------------------------------------------------------------------- time helpers
#
# Pure conversions between a builtin_interfaces/Time value ({'sec', 'nanosec'}) and the various
# ways the time wizard lets you enter one. The wall clock is never read here — the popup passes
# ``time.time()`` in — so these stay deterministic and unit-testable without a running app.


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


# --------------------------------------------------------------------------- time wizard


class TimeWizardPopup(ModalScreen[object]):
    """Fill a builtin_interfaces/Time value. Dismisses with the value, or None if cancelled.

    Every mode is just an input method; the dismissed value is either the ``'now'`` magic string
    (stamped at send time) or a concrete ``{'sec', 'nanosec'}`` dict. The wall-clock and relative
    modes resolve against the *system* clock at Apply time (not ROS sim-time).
    """

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel', priority=True),
    ]

    DEFAULT_CSS = """
    TimeWizardPopup { align: center middle; }
    TimeWizardPopup #time-wizard-box {
        width: 64; height: auto; border: round $primary; padding: 1 2;
    }
    TimeWizardPopup Static { height: 1; }
    TimeWizardPopup RadioSet { height: auto; margin-bottom: 1; }
    TimeWizardPopup .field-row { height: 3; width: 1fr; }
    TimeWizardPopup .field-row Static { width: 12; content-align: left middle; height: 3; }
    TimeWizardPopup .field-row Input { width: 1fr; }
    TimeWizardPopup #time-wizard-result { color: $success; text-style: bold; margin-top: 1; }
    TimeWizardPopup #time-wizard-error { color: $error; text-style: bold; }
    TimeWizardPopup #time-wizard-buttons { height: 3; margin-top: 1; }
    TimeWizardPopup #time-wizard-buttons Button {
        margin-right: 1; background: $surface; color: $text; border: round $primary;
    }
    TimeWizardPopup #time-wizard-buttons Button:focus {
        background: $primary; color: $text; border: round $primary; text-style: bold;
    }
    """

    _MODES = ('now', 'seconds', 'wallclock', 'relative')
    # Per-mode input rows: (field_id, label, placeholder). 'now' has no row.
    _LAYOUT = {
        'seconds': (('time-seconds', 'seconds', 'e.g. 2.5'),),
        'wallclock': (('time-wallclock', 'date/time', 'YYYY-MM-DD HH:MM:SS'),),
        'relative': (('time-offset', 'offset s', 'e.g. -5 or 10'),),
    }

    def __init__(self, current_value: Any = None):
        super().__init__()
        self._mode, seconds = _parse_time(current_value)
        self._values = {
            'time-seconds': seconds,
            'time-wallclock': '',
            'time-offset': '0.0',
        }

    def compose(self):
        with Vertical(id='time-wizard-box'):
            yield Static('Time — choose how to enter the stamp')
            with RadioSet(id='time-wizard-mode'):
                yield RadioButton('now — stamped at send time', value=self._mode == 'now')
                yield RadioButton('seconds — decimal seconds since epoch', value=self._mode == 'seconds')
                yield RadioButton('wall-clock — local date & time', value=self._mode == 'wallclock')
                yield RadioButton('relative — offset from now (seconds)', value=self._mode == 'relative')
            for mode, rows in self._LAYOUT.items():
                for field_id, label, placeholder in rows:
                    with Horizontal(classes=f'field-row mode-{mode}', id=f'{field_id}-row'):
                        yield Static(label)
                        yield Input(value=self._values[field_id], placeholder=placeholder, id=field_id)
            yield Static('', id='time-wizard-result')
            yield Static('', id='time-wizard-error')
            with Horizontal(id='time-wizard-buttons'):
                yield Button('Apply', id='time-wizard-apply')
                yield Button('Cancel', id='time-wizard-cancel')

    def on_mount(self) -> None:
        self._refresh_visibility()
        self._refresh_result()

    def _current_mode(self) -> str:
        index = self.query_one('#time-wizard-mode', RadioSet).pressed_index
        return self._MODES[index] if 0 <= index < len(self._MODES) else 'now'

    def _refresh_visibility(self) -> None:
        mode = self._current_mode()
        for candidate in self._LAYOUT:
            for row in self.query(f'.mode-{candidate}'):
                row.display = candidate == mode

    @on(RadioSet.Changed, '#time-wizard-mode')
    def _on_mode_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._refresh_visibility()
        self._set_error('')
        self._refresh_result()

    @on(Input.Changed)
    def _on_input_changed(self, event: Input.Changed) -> None:
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
        mode = self._current_mode()
        if mode == 'now':
            return 'now'
        if mode == 'seconds':
            try:
                return seconds_str_to_stamp(self.query_one('#time-seconds', Input).value)
            except ValueError:
                if strict:
                    self._set_error('enter non-negative seconds, e.g. 2.5')
                return None
        if mode == 'wallclock':
            try:
                return epoch_to_stamp(parse_wallclock(self.query_one('#time-wallclock', Input).value))
            except ValueError:
                if strict:
                    self._set_error('use YYYY-MM-DD HH:MM:SS')
                return None
        try:  # relative
            offset = float(self.query_one('#time-offset', Input).value)
        except ValueError:
            if strict:
                self._set_error('offset must be a number of seconds')
            return None
        return epoch_to_stamp(time.time() + offset)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, '#time-wizard-cancel')
    def _cancel_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    @on(Button.Pressed, '#time-wizard-apply')
    def _apply_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        value = self._compute(strict=True)
        if value is not None:
            self.dismiss(value)

    def _set_error(self, text: str) -> None:
        self.query_one('#time-wizard-error', Static).update(text)


# The registry keyed by the type label from get_fields_and_field_types() (e.g. 'std_msgs/Header').
# builtin_interfaces/Time is intentionally absent: the Time wizard is reached only as a nested
# sub-wizard from the Header wizard (matched_wizard returns the outermost match, so a Time entry
# here could never fire inside a header anyway). Point/etc. plug in here with no other changes.
WIZARDS: dict[str, type[ModalScreen]] = {
    'std_msgs/Header': HeaderWizardPopup,
    'geometry_msgs/Quaternion': QuaternionWizardPopup,
}
