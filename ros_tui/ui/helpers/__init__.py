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

"""The field helpers: `f` on a field row opens a small popup that fills the value for you.

Pure Python (no textual, no rclpy). A row has a helper when its type is in `BY_TYPE`, or when it is a
whole number with enum constants (`helper_kind`). The kinds:

- enum: pick one of the field's constants, "● 1 WARN = 1".
- quat (Quaternion): x y z w, roll pitch yaw (°), yaw only (°), or axis + angle (°).
- header (Header): auto, now (with a frame), or manual (a frame and a stamp in seconds).
- time (Time): now, seconds, or sec + nanosec.

Every kind but enum is a strip of modes, each with its own fields to type (`Mode`). `Helper` holds
the popup's state; `press` moves and types, and `result` is the value to write into the row with
the preview line, or None while the fields don't make one ("= fix the values first"). The entry
that opened the helper writes the value (entries/message.py), so it validates and undoes like an
edit. The maths and parsing are in the modules next to this one.
"""

import dataclasses
import math
from typing import Any, NamedTuple

from ros_tui.constants import HEADER_AUTO, TIME_NOW
from ros_tui.ui.fields import COMPACT, LEAF, Row, flow_yaml
from ros_tui.ui.helpers.header import parse_header
from ros_tui.ui.helpers.quaternion import clean_quat, normalize_quat, quat_about_axis, quat_from_euler, yaw_of
from ros_tui.ui.helpers.time import parse_time, seconds_str_to_stamp, stamp_to_seconds_str

ENUM, QUAT, HEADER, TIME = 'enum', 'quat', 'header', 'time'
NAMES = {ENUM: 'Enum', QUAT: 'Quaternion', HEADER: 'Header', TIME: 'Time'}
BY_TYPE = {'geometry_msgs/Quaternion': QUAT, 'std_msgs/Header': HEADER, 'builtin_interfaces/Time': TIME}
NANOSEC = 1_000_000_000
DIGITS = 6  # What a typed number is rounded to when it is shown again.


class Mode(NamedTuple):
    name: str  # As the mode strip shows it.
    fields: tuple[str, ...]  # What you type in this mode.
    note: str = ''  # A line under the strip saying what the mode does.


MODES = {  # Each helper kind's modes, in strip order.
    QUAT: (Mode('x y z w', ('x', 'y', 'z', 'w')), Mode('roll pitch yaw (°)', ('roll', 'pitch', 'yaw')),
           Mode('yaw only (°)', ('yaw',)), Mode('axis + angle (°)', ('ax', 'ay', 'az', 'angle'))),
    HEADER: (Mode('auto', (), 'empty header, stamped at send'), Mode('now', ('frame_id',), 'stamped at send, with a frame'),
             Mode('manual', ('frame_id', 'stamp'), 'your own stamp in seconds')),
    TIME: (Mode('now', (), 'stamped at send'), Mode('seconds', ('seconds',), 'seconds since the epoch, e.g. 2.5'),
           Mode('sec + nanosec', ('sec', 'nanosec'), 'the two fields as they are sent')),
}
MODE_KEYS = 'tab next way to enter it · ↑↓ field · type to change · enter applies · esc cancels'


class Result(NamedTuple):
    value: Any  # Plain data for the row: an int, a {x, y, z, w} dict, 'auto', …
    label: str  # The preview after "= ".


def helper_kind(row: Row | None) -> str | None:
    """The kind of helper `row` has (ENUM, QUAT, HEADER, TIME), or None."""
    if row is None:
        return None
    if row.shape == COMPACT:
        return BY_TYPE.get(row.label)
    return ENUM if row.shape == LEAF and row.node.constants else None


def helper_name(row: Row | None) -> str | None:
    """'Quaternion' for a row with the Quaternion helper: its `[f …]` badge and the footer's hint."""
    return NAMES.get(helper_kind(row))


def number_text(value: float) -> str:
    """A number as a helper field shows it: rounded, always with a decimal point ('0.0', '90.0')."""
    value = round(value, DIGITS)
    return repr(0.0 if value == 0 else float(value))


@dataclasses.dataclass
class Helper:
    """The open helper popup: the row it fills, the mode and field it is on, and what was typed."""

    kind: str  # ENUM, QUAT, HEADER or TIME.
    field: str = ''  # The row's field as the user sees it ('pose.orientation').
    type: str = ''  # The row's type as its hint shows it ('Quaternion', 'uint8').
    choices: tuple[tuple[str, int], ...] = ()  # An enum's constants.
    mode: int = 0
    cur: int = 0  # The field being typed, or the enum option picked.
    values: dict[str, str] = dataclasses.field(default_factory=dict)  # Field -> its typed text.
    dirty: set[str] = dataclasses.field(default_factory=set)  # Fields typed into since the mode was picked.

    @staticmethod
    def open(row: Row | None) -> 'Helper | None':
        """The helper for `row`, starting from its value; None without one."""
        kind = helper_kind(row)
        if kind is None:
            return None
        helper = Helper(kind, row.field, row.hint, tuple(row.node.constants or ()))
        OPENERS[kind](helper, row.value)
        return helper

    @property
    def name(self) -> str:
        return NAMES[self.kind]

    def modes(self) -> tuple[Mode, ...]:
        return MODES.get(self.kind, ())

    def fields(self) -> tuple[str, ...]:
        modes = self.modes()
        return modes[self.mode].fields if modes else ()

    def note(self) -> str:
        modes = self.modes()
        return modes[self.mode].note if modes else ''

    def jump_keys(self) -> str:
        """The digits that jump to an enum's options: '0–3' (only 0–9 jump)."""
        last = min(len(self.choices), 10) - 1
        return f'0–{last}' if last > 0 else '0'

    def keys(self) -> str:
        """The key hint line at the bottom of the popup."""
        if self.kind == ENUM:
            return f'j k or ↑↓ pick · {self.jump_keys()} jump · enter applies · esc cancels'
        return MODE_KEYS

    def press(self, key: str, char: str | None) -> None:
        """A key in the popup (enter and esc are the entry's): pick, move, change the mode, type."""
        if self.kind == ENUM:
            self._pick(key, char)
            return
        fields = self.fields()
        if key in ('tab', 'shift+tab'):
            self.mode = (self.mode + (1 if key == 'tab' else -1)) % len(self.modes())
            self.cur = 0
            self.dirty = set()
        elif key in ('down', 'right'):
            self.cur = min(max(0, len(fields) - 1), self.cur + 1)
        elif key in ('up', 'left'):
            self.cur = max(0, self.cur - 1)
        elif fields and key == 'backspace':
            name = fields[self.cur]
            self.values[name] = self.values[name][:-1]
            self.dirty.add(name)
        elif fields and char is not None:
            name = fields[self.cur]
            if name not in self.dirty:  # The first key replaces the value.
                self.values[name] = ''
                self.dirty.add(name)
            self.values[name] += char

    def _pick(self, key: str, char: str | None) -> None:
        """An enum's keys: j / k (↓ ↑, tab) step through the options, a digit jumps to one."""
        count = len(self.choices)
        if key in ('j', 'down', 'tab'):
            self.cur = (self.cur + 1) % count
        elif key in ('k', 'up', 'shift+tab'):
            self.cur = (self.cur - 1) % count
        elif char and char.isdigit() and int(char) < count:
            self.cur = int(char)

    def result(self) -> Result | None:
        """What enter writes into the row, or None while the fields don't make a value."""
        return RESULTS[self.kind](self)

    def numbers(self) -> list[float] | None:
        """The current mode's fields as finite numbers, or None if one isn't."""
        try:
            numbers = [float(self.values[name]) for name in self.fields()]
        except ValueError:
            return None
        return numbers if all(math.isfinite(number) for number in numbers) else None


# ---------- enum ----------
def _open_enum(helper: Helper, value: Any) -> None:
    helper.cur = next((index for index, (_, number) in enumerate(helper.choices) if number == value), 0)


def _enum_result(helper: Helper) -> Result:
    name, number = helper.choices[helper.cur]
    return Result(number, f'{number}  ({name})')


# ---------- quaternion ----------
def _open_quat(helper: Helper, value: Any) -> None:
    value = value if isinstance(value, dict) else {}
    x, y, z, w = (float(value.get(name, 1.0 if name == 'w' else 0.0)) for name in 'xyzw')
    numbers = {'x': x, 'y': y, 'z': z, 'w': w, 'roll': 0.0, 'pitch': 0.0, 'yaw': math.degrees(yaw_of(x, y, z, w)),
               'ax': 0.0, 'ay': 0.0, 'az': 1.0, 'angle': 0.0}
    helper.values = {name: number_text(number) for name, number in numbers.items()}


def _quat_result(helper: Helper) -> Result | None:
    numbers = helper.numbers()
    if numbers is None:
        return None
    if helper.mode == 0:  # x y z w
        quat = normalize_quat(*numbers)
    elif helper.mode == 1:  # roll pitch yaw
        quat = quat_from_euler(*map(math.radians, numbers))
    elif helper.mode == 2:  # yaw only
        quat = quat_from_euler(0.0, 0.0, math.radians(numbers[0]))
    else:  # axis + angle
        quat = quat_about_axis(*numbers[:3], math.radians(numbers[3]))
    value = clean_quat(*quat)
    return Result(value, flow_yaml(value))


# ---------- header ----------
def _open_header(helper: Helper, value: Any) -> None:
    mode, frame_id, stamp = parse_header(value)
    helper.mode = ('auto', 'now', 'manual').index(mode)
    helper.values = {'frame_id': frame_id or 'map', 'stamp': stamp_to_seconds_str(stamp) if stamp else '0.0'}


def _header_result(helper: Helper) -> Result | None:
    frame_id = helper.values['frame_id']
    if helper.mode == 0:
        return Result(HEADER_AUTO, 'auto — stamped when sent')
    if helper.mode == 1:
        return Result({'stamp': TIME_NOW, 'frame_id': frame_id}, f'stamp: now · frame_id: {frame_id}')
    try:
        stamp = seconds_str_to_stamp(helper.values['stamp'])
    except ValueError:
        return None
    return Result({'stamp': stamp, 'frame_id': frame_id},
                  f'stamp: {stamp["sec"]} s {stamp["nanosec"]} ns · frame_id: {frame_id}')


# ---------- time ----------
def _open_time(helper: Helper, value: Any) -> None:
    mode, seconds = parse_time(value)
    helper.mode = 0 if mode == 'now' else 1
    stamp = value if isinstance(value, dict) else {}
    helper.values = {'seconds': seconds, 'sec': str(stamp.get('sec', 0)), 'nanosec': str(stamp.get('nanosec', 0))}


def _time_result(helper: Helper) -> Result | None:
    if helper.mode == 0:
        return Result(TIME_NOW, 'now — stamped when sent')
    if helper.mode == 1:
        try:
            stamp = seconds_str_to_stamp(helper.values['seconds'])
        except ValueError:
            return None
    else:
        try:
            stamp = {'sec': int(helper.values['sec']), 'nanosec': int(helper.values['nanosec'])}
        except ValueError:
            return None
        if stamp['sec'] < 0 or not 0 <= stamp['nanosec'] < NANOSEC:
            return None
    return Result(stamp, f'sec: {stamp["sec"]} · nanosec: {stamp["nanosec"]}')


OPENERS = {ENUM: _open_enum, QUAT: _open_quat, HEADER: _open_header, TIME: _open_time}
RESULTS = {ENUM: _enum_result, QUAT: _quat_result, HEADER: _header_result, TIME: _time_result}
