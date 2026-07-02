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

Read side (Phase 1): synthesize editor defaults from an advertised schema, render decoded
messages to truncated YAML, and CDR-decode incoming payloads. The write side (``build`` /
``serialize``) is added in Phase 2.
"""

import dataclasses
from typing import Any

import numpy
import yaml
from rosbags.interfaces import Nodetype

from ros_tui.constants import (
    TRUNCATE_ARRAY_ELEMENTS,
    TRUNCATE_RENDER_LINES,
    TRUNCATE_STRING_CHARS,
)
from ros_tui.contracts import IntrospectionError, TimeSetter
from ros_tui.foxglove.typestore import FoxgloveTypestore, normalize_typename

_FLOAT_BASES = frozenset({'float32', 'float64'})
_STRING_BASES = frozenset({'string', 'wstring'})


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
        tree = self._default_value((Nodetype.NAME, root))
        text = _dump_yaml(tree) if tree else '# (no fields)\n'
        return text

    def build(
        self, kind: str, type_name: str, values: Any
    ) -> tuple[Any, tuple[TimeSetter, ...]]:
        # Phase 2 fills this in (construct a rosbags message + FieldError validation).
        raise IntrospectionError('publishing / service calls over Foxglove are not yet supported')

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

    def root_typename(self, kind: str, type_name: str) -> str:
        """The rosbags key for the user-fillable payload of a msg/srv/action type string."""
        if kind == 'srv':
            return normalize_typename(type_name, 'srv') + '_Request'
        if kind == 'action':
            # The protocol has no actions and the Actions tab is hidden on this backend.
            raise IntrospectionError('actions are not supported over Foxglove')
        return normalize_typename(type_name)

    # -------------------------------------------------------------- defaults (schema-driven)

    def _default_value(self, node) -> Any:
        nodetype, info = node
        if nodetype == Nodetype.BASE:
            return _default_base(info[0])
        if nodetype == Nodetype.NAME:
            _consts, fields = self._ts.fielddefs(info)
            return {name: self._default_value(ftype) for name, ftype in fields}
        if nodetype == Nodetype.ARRAY:
            subtype, length = info
            return [self._default_value(subtype) for _ in range(length)]
        if nodetype == Nodetype.SEQUENCE:
            return []
        return None

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
    return 0  # every integer type, plus octet/char


def _dump_yaml(plain: Any) -> str:
    return yaml.safe_dump(
        plain, sort_keys=False, default_flow_style=False, allow_unicode=True, width=2**31 - 1
    )
