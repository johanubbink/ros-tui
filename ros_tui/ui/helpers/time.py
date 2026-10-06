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

"""Conversions between a builtin_interfaces/Time value (``{'sec', 'nanosec'}``) and the ways the
Time and Header helpers let you type one.

None of them reads the wall clock, so they stay deterministic.
"""

from typing import Any


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


def stamp_to_seconds_str(stamp: dict[str, int]) -> str:
    """Render ``{'sec', 'nanosec'}`` as a trimmed decimal-seconds string (inverse of parse)."""
    sec = int(stamp.get('sec', 0))
    nanosec = int(stamp.get('nanosec', 0))
    if nanosec == 0:
        return str(sec)
    return f'{sec}.{nanosec:09d}'.rstrip('0')


def parse_time(value: Any) -> tuple[str, str]:
    """Best-effort (mode, seconds_str) prefill from a time field value: 'now' or 'seconds'."""
    if isinstance(value, dict) and ('sec' in value or 'nanosec' in value):
        return 'seconds', stamp_to_seconds_str(value)
    return 'now', '0.0'
