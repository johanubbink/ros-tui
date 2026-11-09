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

"""The type labels and field paths of messages, as plain strings. No rosidl, no rclpy.

A type label is how a message class names a field's type (`get_fields_and_field_types`): a
primitive ('int64', 'double', 'boolean', 'string<=5'), a message ('geometry_msgs/Point'), a fixed
array ('double[9]') or a sequence ('sequence<double>', bounded 'sequence<double, 3>').
`array_info` reads the array grammar, `short_type` shortens a label for a hint.

A field path names one field inside a message, as a tuple ('points', 1, 'x') or as the text the user
reads and `message_yaml.FieldError` reports, 'points[1].x' (`path_text`, `parse_path`).

The stamp-at-send words: a Header field holding HEADER_AUTO, or a Time field holding TIME_NOW, is
stamped with the time the message is sent (`message_yaml.build_message`).
"""

import re
from dataclasses import dataclass
from typing import NamedTuple

HEADER_TYPE = 'std_msgs/Header'
TIME_TYPE = 'builtin_interfaces/Time'
HEADER_AUTO = 'auto'  # A std_msgs/Header: stamped, with an empty frame_id.
TIME_NOW = 'now'  # A builtin_interfaces/Time, such as a header's stamp.
STAMP_WORDS = {HEADER_TYPE: HEADER_AUTO, TIME_TYPE: TIME_NOW}  # Type label -> its stamp-at-send word.

FLOAT_TYPES = frozenset({'float', 'double', 'float32', 'float64'})
INTEGER_TYPES = frozenset({'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64',
                           'byte', 'char', 'octet'})
BOOL_TYPE = 'boolean'

Path = tuple[str | int, ...]

_FIXED = re.compile(r'^(?P<element>.+)\[(?P<size>\d+)\]$')
_SEQUENCE = re.compile(r'^sequence<(?P<element>.+?)(?:, ?(?P<bound>\d+))?>$')
_PATH_PART = re.compile(r'([^.\[\]]+)|\[(\d+)\]')


@dataclass(frozen=True)
class FieldNode:
    """A field in a message's static structure: its name, type label, and nested fields.

    ``constants`` holds the enum choices ``(name, int_value)`` that apply to this field, when
    the field is an integer enum backed by message constants (`message_yaml` finds them); empty
    otherwise. The Enum helper offers these as its choices.
    """

    name: str
    type_label: str
    children: tuple['FieldNode', ...] = ()
    constants: tuple[tuple[str, int], ...] = ()


class ArrayInfo(NamedTuple):
    element: str  # The element's type label.
    size: int | None  # The size of a fixed array (T[N]), else None.
    bound: int | None  # The most elements a bounded sequence (sequence<T, N>) holds, else None.


def array_info(label: str) -> ArrayInfo | None:
    """What an array label says about its elements, or None when `label` is no array."""
    match = _SEQUENCE.match(label)
    if match:
        return ArrayInfo(match['element'], None, int(match['bound']) if match['bound'] else None)
    match = _FIXED.match(label)
    return ArrayInfo(match['element'], int(match['size']), None) if match else None


def element_of(node: FieldNode) -> FieldNode:
    """The type of one element of the array field `node`, under the array's name."""
    return FieldNode(node.name, array_info(node.type_label).element, node.children, node.constants)


def short_type(label: str) -> str:
    """The type as a row's hint shows it: 'int64', 'Point', 'double[9]', 'Point32[]', 'double[<=3]'."""
    info = array_info(label)
    if info:
        size = info.size if info.size is not None else f'<={info.bound}' if info.bound else ''
        return f'{short_type(info.element)}[{size}]'
    return label.rsplit('/', 1)[-1]


def is_string(label: str) -> bool:
    return label.startswith(('string', 'wstring'))


def path_text(path: Path) -> str:
    """A path as the user reads it and FieldError reports it: 'pose.position', 'points[1].x'."""
    text = ''
    for part in path:
        text += f'[{part}]' if isinstance(part, int) else (f'.{part}' if text else part)
    return text


def parse_path(text: str) -> Path:
    return tuple(int(index) if index else name for name, index in _PATH_PART.findall(text))


def within(path: str, field: str) -> bool:
    """True when the field path `path` is `field` or inside it."""
    return path == field or path.startswith((field + '.', field + '['))
