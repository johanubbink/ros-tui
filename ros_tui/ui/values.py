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

"""One value as text: shown as flow YAML, and typed text read back as a value of its type.

Pure Python (no textual, no rclpy). `flow_yaml` writes a value on one line so that YAML reads it back
to the same value; `parse_scalar`, `parse_list`, `parse_map` and `enum_value` read what the user
typed, by the type label (`ros.schema`), or raise ValueError with the message the user sees, which
names the field and quotes the text ("a needs a whole number, got "x""). Field rows and node
parameters both read their values with these. `describe` words a validator's FieldError the same
way; `summary` and `enum_matches` are the one-line views of a message and an enum.
"""

import math
import re
from typing import Any

import yaml

from ros_tui.ros.schema import BOOL_TYPE, FLOAT_TYPES, is_string

_FIELD_PREFIX = re.compile(r"^(?:The '[^']*' field |byte field )")


def _scalar_yaml(value: Any) -> str | None:
    """A bool, int or float as yaml.safe_dump writes it (without the cost of a dump), else None."""
    kind = type(value)
    if kind is bool:
        return 'true' if value else 'false'
    if kind is int:
        return str(value)
    if kind is not float:
        return None
    if value != value:
        return '.nan'
    if value in (math.inf, -math.inf):
        return '.inf' if value > 0 else '-.inf'
    text = repr(value).lower()
    return text.replace('e', '.0e', 1) if '.' not in text and 'e' in text else text


def flow_yaml(value: Any) -> str:
    """`value` as one line of YAML that parses back to it: '5.0', '[1, 2]', "{x: 1.0, y: 'a b'}"."""
    text = _scalar_yaml(value)
    if text is not None:
        return text
    if type(value) is list:  # A list of numbers (and bools) is the common non-scalar: no dump either.
        items = [_scalar_yaml(item) for item in value]
        if None not in items:
            return f'[{", ".join(items)}]'
    text = yaml.safe_dump(value, default_flow_style=True, sort_keys=False, width=math.inf, allow_unicode=True).strip()
    if text.endswith('\n...'):  # safe_dump ends a bare scalar with a document-end marker.
        text = text[:-len('\n...')].rstrip()
    return text


def summary(values: dict, limit: int) -> str:
    """The top-level fields as one line for the activity strip: 'a: 19, b: 23' (cut at `limit`)."""
    text = ', '.join(f'{name}: {flow_yaml(value)}' for name, value in values.items())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def describe(error: Any, typed: str = '') -> str:
    """A validator's FieldError as the user reads it: the field first, then what is wrong."""
    detail = _FIELD_PREFIX.sub('', str(getattr(error, 'detail', error)))
    path = getattr(error, 'path', '')
    if not detail.startswith('must'):
        return f'{path}: {detail}' if path else detail
    if typed and 'got' not in detail:
        detail += f', got "{typed}"'
    return f'{path} {detail}'


def _parse_string(text: str) -> str:
    """Bare text is the string itself; text in quotes is read as a YAML string ('' is empty)."""
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in '\'"':
        try:
            value = yaml.safe_load(stripped)
        except yaml.YAMLError:
            return text
        return value if isinstance(value, str) else text
    return text


def _load(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def parse_list(field: str, text: str) -> list:
    """`text` read as a YAML list (its elements unchecked), or ValueError naming the field. A node's
    array parameters are read by it too (entries/node.parse_value)."""
    value = _load(text.strip())
    if not isinstance(value, list):
        raise ValueError(f'{field} needs a list like [1, 2], got "{text.strip()}"')
    return value


def parse_map(field: str, needs: str, text: str) -> dict:
    """`text` read as a YAML flow map (its keys and values unchecked), or ValueError naming the field
    and what it `needs` ('{x: …, y: …}')."""
    shown = text.strip()
    value = _load(shown)
    if not isinstance(value, dict):
        raise ValueError(f'{field} needs {needs}, got "{shown}"')
    return value


def parse_scalar(label: str, field: str, text: str) -> Any:
    """`text` read as a value of the primitive type `label`, or ValueError naming the field. Node
    parameters are read by it too (entries/node.parse_value)."""
    shown = text.strip()
    if is_string(label):
        return _parse_string(text)
    if label == BOOL_TYPE:
        if shown.lower() in ('true', 'false'):
            return shown.lower() == 'true'
        raise ValueError(f'{field} needs true or false, got "{shown}"')
    if label in FLOAT_TYPES:
        try:
            return float(shown)  # Also 1e-3, nan and inf.
        except ValueError:
            raise ValueError(f'{field} needs a number, got "{shown}"') from None
    number = _whole_number(shown)
    if number is None:
        raise ValueError(f'{field} needs a whole number, got "{shown}"')
    return number


def enum_value(constants: tuple, field: str, text: str) -> int:
    """`text` typed into an enum field: a constant's name or the start of one, in any case ('err'
    is ERROR), or a number. ValueError naming the field and its names otherwise."""
    typed = text.strip()
    lowered = typed.lower()
    match = (next((number for name, number in constants if name.lower() == lowered), None)
             if lowered else None)
    if match is None and lowered:
        match = next((number for name, number in constants if name.lower().startswith(lowered)), None)
    if match is not None:
        return match
    number = _whole_number(typed)
    if number is None:
        names = ' / '.join(name for name, _ in constants)
        raise ValueError(f'{field} needs {names} or a number, got "{typed}"')
    return number


def enum_matches(constants: tuple, text: str) -> str:
    """The completion next to an enum field being typed: the constants that `text` could mean,
    'OK=0  WARN=1  ERROR=2  STALE=3 · type a name or number'."""
    typed = text.strip().lower()
    matches = [f'{name}={number}' for name, number in constants
               if not typed or name.lower().startswith(typed) or str(number) == typed]
    return ('  '.join(matches) if matches else 'no match') + ' · type a name or number'


def _whole_number(text: str) -> int | None:
    """Decimal, so a typed 019 is 19 (YAML would read 017 as octal); 5.0 is whole too."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None
