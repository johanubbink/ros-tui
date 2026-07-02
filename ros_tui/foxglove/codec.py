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

"""The Foxglove :class:`~ros_tui.contracts.MessageCodec`, backed by a rosbags type store.

Read side: synthesize editor defaults from an advertised schema, render decoded messages to
truncated YAML, and CDR-decode incoming payloads. Write side: build a checked rosbags message
from the editor's YAML (validating types/ranges/sizes with :class:`FieldError`, mirroring the
native codec) and CDR-encode it. All of this is schema-driven off the ``ros2msg`` definitions
the server advertised, so no ROS message packages are needed locally.
"""

import dataclasses
import functools
import math
from typing import Any

import numpy
import yaml
from rosbags.interfaces import Nodetype

from ros_tui.constants import (
    TRUNCATE_ARRAY_ELEMENTS,
    TRUNCATE_RENDER_LINES,
    TRUNCATE_STRING_CHARS,
)
from ros_tui.contracts import FieldError, IntrospectionError, TimeSetter
from ros_tui.foxglove.typestore import (
    FoxgloveTypestore,
    normalize_typename,
    service_message_typename,
)

_FLOAT_BASES = frozenset({'float32', 'float64'})
_STRING_BASES = frozenset({'string', 'wstring'})
_TIME_TYPE = 'builtin_interfaces/msg/Time'
_HEADER_TYPE = 'std_msgs/msg/Header'

# Integer ranges by ros2 base type. byte/char are octets in [0, 255].
_INT_RANGES = {
    'int8': (-128, 127),
    'uint8': (0, 255),
    'byte': (0, 255),
    'char': (0, 255),
    'int16': (-32768, 32767),
    'uint16': (0, 65535),
    'int32': (-(2**31), 2**31 - 1),
    'uint32': (0, 2**32 - 1),
    'int64': (-(2**63), 2**63 - 1),
    'uint64': (0, 2**64 - 1),
}
_DTYPES = {
    'bool': numpy.bool_,
    'int8': numpy.int8,
    'uint8': numpy.uint8,
    'byte': numpy.uint8,
    'char': numpy.uint8,
    'int16': numpy.int16,
    'uint16': numpy.uint16,
    'int32': numpy.int32,
    'uint32': numpy.uint32,
    'int64': numpy.int64,
    'uint64': numpy.uint64,
    'float32': numpy.float32,
    'float64': numpy.float64,
}


class FoxgloveCodec:
    """Turns advertised schemas + YAML into CDR payloads and renders decoded messages back."""

    def __init__(self, typestore: FoxgloveTypestore):
        self._ts = typestore

    # -------------------------------------------------------------- MessageCodec interface

    def default_yaml(self, kind: str, type_name: str) -> str:
        root = self.root_typename(kind, type_name)
        if not self._ts.has(root):
            raise IntrospectionError(
                f"Cannot load {kind} type '{type_name}': schema not advertised by the server"
            )
        tree = self._default_tree((Nodetype.NAME, root))
        return _dump_yaml(tree) if tree else '# (no fields)\n'

    def build(
        self, kind: str, type_name: str, values: Any
    ) -> tuple[Any, tuple[TimeSetter, ...]]:
        root = self.root_typename(kind, type_name)
        if not self._ts.has(root):
            raise IntrospectionError(
                f"Cannot load {kind} type '{type_name}': schema not advertised by the server"
            )
        setters: list[TimeSetter] = []
        message = self._build_instance(root, values if values is not None else {}, '', setters)
        return message, tuple(setters)

    def render(self, payload: Any) -> str:
        plain = self._to_plain(payload, TRUNCATE_ARRAY_ELEMENTS, TRUNCATE_STRING_CHARS)
        text = _dump_yaml(plain) if plain or plain == {} else '(no fields)'
        lines = text.splitlines()
        if len(lines) > TRUNCATE_RENDER_LINES:
            hidden = len(lines) - TRUNCATE_RENDER_LINES
            lines = lines[:TRUNCATE_RENDER_LINES] + [f'… ({hidden} more lines)']
        return '\n'.join(lines)

    # -------------------------------------------------------------- bridge-side helpers

    def deserialize(self, typename: str, cdr: bytes) -> Any:
        return self._ts.deserialize(cdr, typename)

    def serialize(self, payload: Any) -> bytes:
        """CDR-encode a message built by :meth:`build` (self-describing via ``__msgtype__``)."""
        return self._ts.serialize(payload, payload.__msgtype__)

    def root_typename(self, kind: str, type_name: str) -> str:
        """The rosbags key for the user-fillable payload of a msg/srv/action type string."""
        if kind == 'srv':
            return service_message_typename(type_name, 'Request')
        if kind == 'action':
            raise IntrospectionError('actions are not supported over Foxglove')
        return normalize_typename(type_name)

    # -------------------------------------------------------------- build (YAML -> message)

    def _build_instance(self, typename: str, values: Any, path: str, setters: list) -> Any:
        if not isinstance(values, dict):
            raise FieldError(
                path.rstrip('.'), f'expected a mapping for {typename}, got {type(values).__name__}'
            )
        _consts, fields = self._ts.fielddefs(typename)
        field_types = dict(fields)
        for key in values:
            if key not in field_types:
                raise FieldError(f'{path}{key}', f"'{key}' is not a field of {typename}")
        message = self._default_instance(typename)
        for name, ftype in fields:
            if name not in values:
                continue  # keep the default
            field_path = f'{path}{name}'
            if self._apply_magic(message, name, ftype, values[name], setters):
                continue
            setattr(message, name, self._coerce(ftype, values[name], field_path, setters))
        return message

    def _apply_magic(self, message, name, ftype, value, setters) -> bool:
        """Handle ``stamp: now`` / ``header: auto``; return True if it consumed the field."""
        nodetype, info = ftype
        if nodetype != Nodetype.NAME:
            return False
        if info == _TIME_TYPE and value == 'now':
            setters.append(functools.partial(setattr, message, name))
            return True
        if info == _HEADER_TYPE and value == 'auto':
            setters.append(functools.partial(setattr, getattr(message, name), 'stamp'))
            return True
        return False

    def _coerce(self, ftype, value, path: str, setters: list) -> Any:
        nodetype, info = ftype
        if nodetype == Nodetype.BASE:
            return _coerce_base(info[0], info[1], value, path)
        if nodetype == Nodetype.NAME:
            return self._build_instance(info, value, f'{path}.', setters)
        if nodetype in (Nodetype.ARRAY, Nodetype.SEQUENCE):
            return self._coerce_array(nodetype, info, value, path, setters)
        raise FieldError(path, 'unsupported field type')

    def _coerce_array(self, nodetype, info, value, path: str, setters: list) -> Any:
        subtype, bound = info
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise FieldError(path, f'expected a list, got {type(value).__name__}')
        if nodetype == Nodetype.ARRAY and len(value) != bound:
            raise FieldError(path, f'expected exactly {bound} elements, got {len(value)}')
        if nodetype == Nodetype.SEQUENCE and bound and len(value) > bound:
            raise FieldError(path, f'expected at most {bound} elements, got {len(value)}')
        sub_node, sub_info = subtype
        if sub_node == Nodetype.BASE and sub_info[0] in _DTYPES and sub_info[0] not in _STRING_BASES:
            checked = [
                _coerce_base(sub_info[0], sub_info[1], item, f'{path}[{i}]')
                for i, item in enumerate(value)
            ]
            return numpy.array(checked, dtype=_DTYPES[sub_info[0]])
        return [
            self._coerce(subtype, item, f'{path}[{i}]', setters) for i, item in enumerate(value)
        ]

    # -------------------------------------------------------------- default instances

    def _default_instance(self, typename: str) -> Any:
        _consts, fields = self._ts.fielddefs(typename)
        kwargs = {name: self._default_field(ftype) for name, ftype in fields}
        return self._ts.message_class(typename)(**kwargs)

    def _default_field(self, ftype) -> Any:
        nodetype, info = ftype
        if nodetype == Nodetype.BASE:
            return _default_base(info[0])
        if nodetype == Nodetype.NAME:
            return self._default_instance(info)
        subtype, length = info
        sub_node, sub_info = subtype
        if sub_node == Nodetype.BASE and sub_info[0] in _DTYPES and sub_info[0] not in _STRING_BASES:
            count = length if nodetype == Nodetype.ARRAY else 0
            return numpy.zeros(count, dtype=_DTYPES[sub_info[0]])
        if nodetype == Nodetype.ARRAY:
            return [self._default_field(subtype) for _ in range(length)]
        return []

    # -------------------------------------------------------------- defaults tree (for YAML)

    def _default_tree(self, node) -> Any:
        nodetype, info = node
        if nodetype == Nodetype.BASE:
            return _default_base(info[0])
        if nodetype == Nodetype.NAME:
            _consts, fields = self._ts.fielddefs(info)
            return {name: self._default_tree(ftype) for name, ftype in fields}
        if nodetype == Nodetype.ARRAY:
            subtype, length = info
            return [self._default_tree(subtype) for _ in range(length)]
        return []

    # -------------------------------------------------------------- rendering (message -> plain)

    def _to_plain(self, value: Any, max_array: int, max_str: int) -> Any:
        if isinstance(value, numpy.ndarray):
            return self._plain_sequence(value.tolist(), len(value), max_array, max_str)
        if isinstance(value, (bytes, bytearray)):
            return self._plain_sequence(list(value), len(value), max_array, max_str)
        if dataclasses.is_dataclass(value) and hasattr(value, '__msgtype__'):
            return {
                name: self._to_plain(getattr(value, name), max_array, max_str)
                for name in type(value).__dataclass_fields__
                if name != '__msgtype__'
            }
        if isinstance(value, (list, tuple)):
            return self._plain_sequence(list(value), len(value), max_array, max_str)
        if isinstance(value, numpy.generic):
            return value.item()
        if isinstance(value, str) and len(value) > max_str:
            return value[:max_str] + f'… ({len(value)} chars total)'
        return value

    def _plain_sequence(self, items: list, total: int, max_array: int, max_str: int) -> list:
        truncated = total > max_array
        shown = items[:max_array] if truncated else items
        plain = [self._to_plain(item, max_array, max_str) for item in shown]
        if truncated:
            plain.append(f'… ({total} total)')
        return plain


def _default_base(basename: str) -> Any:
    if basename in _STRING_BASES:
        return ''
    if basename == 'bool':
        return False
    if basename in _FLOAT_BASES:
        return 0.0
    return 0  # every integer type, plus byte/char


def _coerce_base(basename: str, bound: int, value: Any, path: str) -> Any:
    if basename in _STRING_BASES:
        text = value if isinstance(value, str) else str(value)
        if bound and len(text) > bound:
            raise FieldError(path, f'string exceeds max length {bound}')
        return text
    if basename == 'bool':
        if not isinstance(value, bool):
            raise FieldError(path, f'expected a boolean, got {value!r}')
        return value
    if basename in _FLOAT_BASES:
        return _coerce_float(basename, value, path)
    return _coerce_int(basename, value, path)


def _coerce_int(basename: str, value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FieldError(path, f'expected an integer, got {value!r}')
    if isinstance(value, float):
        if not value.is_integer():
            raise FieldError(path, f'expected an integer, got {value}')
        value = int(value)
    low, high = _INT_RANGES[basename]
    if not low <= value <= high:
        raise FieldError(path, f'must be an integer in [{low}, {high}], got {value}')
    return value


def _coerce_float(basename: str, value: Any, path: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise FieldError(path, f'expected a float, got {value!r}') from error
    if basename == 'float32' and math.isfinite(number):
        limit = float(numpy.finfo(numpy.float32).max)
        if not -limit <= number <= limit:
            raise FieldError(path, f'must be a float32 in [{-limit}, {limit}], got {number}')
    return number


def _dump_yaml(plain: Any) -> str:
    return yaml.safe_dump(
        plain, sort_keys=False, default_flow_style=False, allow_unicode=True, width=2**31 - 1
    )
