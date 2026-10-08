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

"""Reading a std_msgs/Header value back into the Header helper's modes.

A header is written as one of three values, which all go through ``build_message``:
'auto' (empty, stamped at send), ``{stamp: now, frame_id: map}`` (stamped at send, with a frame) or
``{stamp: {sec: 2, nanosec: 500000000}, frame_id: map}`` (your own stamp).
"""

from typing import Any

from ros_tui.constants import TIME_NOW


def parse_header(value: Any) -> tuple[str, str, Any]:
    """Best-effort (mode, frame_id, stamp) from a header field value: mode is 'auto', 'now' or
    'manual'; ``stamp`` is a ``{'sec', 'nanosec'}`` dict for a manual header, else ``None``."""
    if not isinstance(value, dict):
        return 'auto', '', None
    frame_id = str(value.get('frame_id', ''))
    stamp = value.get('stamp')
    if stamp == TIME_NOW:
        return 'now', frame_id, None
    if isinstance(stamp, dict):
        return 'manual', frame_id, {
            'sec': int(stamp.get('sec', 0)),
            'nanosec': int(stamp.get('nanosec', 0)),
        }
    return 'auto', frame_id, None
