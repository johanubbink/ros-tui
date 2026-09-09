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

"""Quaternion wizard — enter a geometry_msgs/Quaternion as raw / euler / yaw / axis-angle.

The rotation math is delegated to tf_transformations (the ROS wrapper over transforms3d) so the
conventions match the rest of the ROS ecosystem. It is imported lazily inside each helper so
this module still imports without a ROS environment (the pure math and registry are unit-tested
with no rclpy/tf present).
"""

import math
from typing import Any, Iterable

from textual import on
from textual.widget import Widget
from textual.widgets import RadioButton, RadioSet, Static

from ros_tui.ui.wizards.base import WizardScreen
from ros_tui.ui.wizards.components import ModeForm, pressed_key
from ros_tui.ui.wizards.registry import register


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


@register('geometry_msgs/Quaternion')
class QuaternionWizardPopup(WizardScreen):
    """Fill a geometry_msgs/Quaternion field. Dismisses with ``{x, y, z, w}`` or None if cancelled.

    Every mode is just an input method; the dismissed value is always the normalized quaternion.
    Angles use the shared degrees/radians toggle (hidden in raw-quaternion mode). Euler is ROS
    RPY (roll=X, pitch=Y, yaw=Z, intrinsic ZYX) — the same convention as tf's
    ``quaternion_from_euler``.
    """

    TITLE = 'Quaternion — choose how to enter the rotation'
    PREFIX = 'quat-wizard'

    _UNITS = ('degrees', 'radians')

    def __init__(self, current_value: Any = None):
        super().__init__()
        values = {
            **_parse_quaternion(current_value),
            'euler-roll': '0.0', 'euler-pitch': '0.0', 'euler-yaw': '0.0',
            'yaw-only': '0.0',
            'axis-x': '0.0', 'axis-y': '0.0', 'axis-z': '1.0', 'axis-angle': '0.0',
        }
        self._modes = [
            ('quaternion', 'quaternion — raw x/y/z/w',
             (('quat-x', 'x', values['quat-x'], ''), ('quat-y', 'y', values['quat-y'], ''),
              ('quat-z', 'z', values['quat-z'], ''), ('quat-w', 'w', values['quat-w'], ''))),
            ('euler', 'euler RPY — roll(X)/pitch(Y)/yaw(Z), ROS intrinsic ZYX',
             (('euler-roll', 'roll', values['euler-roll'], ''),
              ('euler-pitch', 'pitch', values['euler-pitch'], ''),
              ('euler-yaw', 'yaw', values['euler-yaw'], ''))),
            ('yaw', 'yaw only — rotation about Z (planar)',
             (('yaw-only', 'yaw', values['yaw-only'], ''),)),
            ('axis_angle', 'axis-angle — axis (x,y,z) + angle',
             (('axis-x', 'axis x', values['axis-x'], ''), ('axis-y', 'axis y', values['axis-y'], ''),
              ('axis-z', 'axis z', values['axis-z'], ''),
              ('axis-angle', 'angle', values['axis-angle'], ''))),
        ]

    def compose_body(self) -> Iterable[Widget]:
        yield ModeForm(self._modes, radio_id='quat-wizard-mode', initial='quaternion')
        with RadioSet(id='quat-wizard-unit'):
            yield RadioButton('degrees', value=True)
            yield RadioButton('radians')
        yield Static('', id='quat-wizard-result', classes='wizard-result')

    def on_mount(self) -> None:
        self._refresh_unit_visibility()
        self._refresh_result()

    @property
    def _form(self) -> ModeForm:
        return self.query_one(ModeForm)

    def _current_unit(self) -> str:
        return pressed_key(self.query_one('#quat-wizard-unit', RadioSet), self._UNITS)

    def _refresh_unit_visibility(self) -> None:
        self.query_one('#quat-wizard-unit', RadioSet).display = self._form.current_mode != 'quaternion'

    @on(ModeForm.Changed)
    def _on_form_changed(self, event: ModeForm.Changed) -> None:
        event.stop()
        self._refresh_unit_visibility()
        self._set_error('')
        self._refresh_result()

    @on(RadioSet.Changed, '#quat-wizard-unit')
    def _on_unit_changed(self, event: RadioSet.Changed) -> None:
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
                values.append(float(self._form.raw(field_id)))
            except ValueError:
                if strict:
                    self._set_error('all fields must be numbers')
                return None
        return values

    def _compute(self, strict: bool) -> dict[str, float] | None:
        mode = self._form.current_mode
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

    def build_value(self) -> Any:
        return self._compute(strict=True)


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
