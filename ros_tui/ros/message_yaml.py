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
Lazy interface-type loading and checked YAML <-> ROS message conversion.

This module deliberately re-implements ``rosidl_runtime_py.set_message_fields`` because the
Jazzy version neither reports the offending field path nor validates ranges/sizes (field
checking is off unless ``ROS_PYTHON_CHECK_FIELDS`` is set, so e.g. ``UInt8(data=300)`` or a
wrong-length fixed array would be sent silently corrupted). Here every (sub)message is built
with ``check_fields=True`` and every failure is wrapped in :class:`FieldError` carrying the
dotted/indexed path (``pose.position.x``, ``points[1].x``).
"""

import array
import functools
import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy
import yaml
from rosidl_parser.definition import (
    AbstractNestedType,
    AbstractString,
    AbstractWString,
    BasicType,
    NamespacedType,
)
from rosidl_runtime_py.convert import get_message_slot_types
from rosidl_runtime_py.import_message import import_message_from_namespaced_type
from rosidl_runtime_py.utilities import get_action, get_message, get_service

from ros_tui.constants import (
    MAX_CONSTANTS_IN_COMMENT,
    TRUNCATE_ARRAY_ELEMENTS,
    TRUNCATE_RENDER_LINES,
    TRUNCATE_STRING_CHARS,
    TYPE_CACHE_SIZE,
)

# A deferred setter receives a builtin_interfaces/msg/Time and stamps it into the message.
TimeSetter = Callable[[Any], None]

_LOADERS = {'msg': get_message, 'srv': get_service, 'action': get_action}
_FLOAT_TYPENAMES = ('float', 'double', 'float32', 'float64')
_HEADER_CLASS = 'std_msgs.msg._header.Header'
_TIME_CLASS = 'builtin_interfaces.msg._time.Time'


class IntrospectionError(Exception):
    """Raised when an interface type cannot be loaded."""


class FieldError(Exception):
    """A value in the user's YAML does not fit the message, located by its field path."""

    def __init__(self, path: str, detail: str):
        self.path = path
        self.detail = detail
        super().__init__(f'{path}: {detail}' if path else detail)


@functools.lru_cache(maxsize=TYPE_CACHE_SIZE)
def import_type(kind: str, type_name: str) -> type:
    """Import an interface class for ``kind`` in ('msg', 'srv', 'action') by its type string."""
    try:
        return _LOADERS[kind](type_name)
    except Exception as error:
        raise IntrospectionError(
            f"Cannot load {kind} type '{type_name}': {error} (interface package not sourced?)"
        ) from error


def request_class(kind: str, interface: type) -> type:
    """Return the user-fillable class: the message itself, srv Request, or action Goal."""
    if kind == 'srv':
        return interface.Request
    if kind == 'action':
        return interface.Goal
    return interface


@functools.lru_cache(maxsize=TYPE_CACHE_SIZE)
def default_yaml(kind: str, type_name: str) -> str:
    """Seed text for the editor: the default message as YAML plus a constants hint."""
    interface = import_type(kind, type_name)
    fillable = request_class(kind, interface)
    plain = message_to_plain(fillable(), seed=True)
    text = _dump_yaml(plain) if plain else '# (no fields)\n'
    constants = _constants_comment(fillable)
    return text + constants


def schema_path(parent_path: str, name: str) -> str:
    """Dotted field path used by the structure tree and to_filtered_yaml (indices collapsed)."""
    return f'{parent_path}.{name}' if parent_path else name


@dataclass(frozen=True)
class FieldNode:
    """A field in a message's static structure: its name, type label, and nested fields.

    ``constants`` holds the enum choices ``(name, int_value)`` that apply to this field, when
    the field is an integer enum backed by message constants (see :func:`_field_enum_choices`);
    empty otherwise. The enum field wizard renders these as a single-choice list.
    """

    name: str
    type_label: str
    children: tuple['FieldNode', ...] = field(default_factory=tuple)
    constants: tuple[tuple[str, int], ...] = ()


@functools.lru_cache(maxsize=TYPE_CACHE_SIZE)
def message_structure(kind: str, type_name: str) -> tuple[FieldNode, ...]:
    """Static field tree for ``kind``/``type_name`` (introspected from the class, no instance)."""
    fillable = request_class(kind, import_type(kind, type_name))
    return _class_fields(fillable, frozenset())


def _class_fields(message_class: type, seen: frozenset) -> tuple[FieldNode, ...]:
    types = message_class.get_fields_and_field_types()
    enum_choices = _field_enum_choices(message_class)
    return tuple(
        FieldNode(name, types[name], _slot_children(slot, seen), enum_choices.get(name, ()))
        for name, slot in zip(types, message_class.SLOT_TYPES)
    )


_INTEGER_SCALAR_TYPES = frozenset(
    {'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64',
     'byte', 'char', 'octet'}
)


def _message_constants(message_class: type) -> list[tuple[str, int]]:
    """Integer enum constants declared on ``message_class`` as ``(name, value)``.

    IDL constants surface as upper-case class attributes; ``int`` ones (e.g. Marker's ``ARROW``)
    are taken as-is, while ``byte``/``octet`` ones (e.g. DiagnosticStatus's ``OK``) arrive as a
    single ``bytes`` and are decoded to their integer value. Booleans and generated internals
    (``_TYPE_SUPPORT``, ``<FIELD>__DEFAULT``) are skipped.
    """
    constants = []
    for name in dir(message_class):
        if not name.isupper() or name.startswith('_') or '__' in name:
            continue
        value = getattr(message_class, name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            constants.append((name, value))
        elif isinstance(value, bytes) and len(value) == 1:
            constants.append((name, value[0]))
    constants.sort(key=lambda item: item[1])  # by value: natural enum order, not dir()'s alpha.
    return constants


def _field_enum_choices(message_class: type) -> dict[str, tuple[tuple[str, int], ...]]:
    """Map each integer field to the enum constants that apply to it.

    Association heuristic: a field takes constants whose names share its upper-case prefix
    (e.g. ``power_supply_status`` -> ``POWER_SUPPLY_STATUS_*``); failing that, if the message has
    exactly one integer field it takes all the constants (the DiagnosticStatus ``level`` case).
    Otherwise it gets none -- so un-prefixed multi-enum messages (e.g. Marker) are left alone
    rather than mis-attributing every constant to every integer field.
    """
    constants = _message_constants(message_class)
    if not constants:
        return {}
    types = message_class.get_fields_and_field_types()
    int_fields = [name for name, label in types.items() if label in _INTEGER_SCALAR_TYPES]
    choices = {}
    for name in int_fields:
        prefixed = tuple((n, v) for n, v in constants if n.startswith(name.upper() + '_'))
        if prefixed:
            choices[name] = prefixed
        elif len(int_fields) == 1:
            choices[name] = tuple(constants)
    return choices


def _slot_children(slot: Any, seen: frozenset) -> tuple['FieldNode', ...]:
    value_type = slot.value_type if isinstance(slot, AbstractNestedType) else slot
    if not isinstance(value_type, NamespacedType):
        return ()
    nested = import_message_from_namespaced_type(value_type)
    key = f'{nested.__module__}.{nested.__name__}'
    if key in seen:
        return ()  # Defensive: ROS IDL messages are not normally cyclic.
    return _class_fields(nested, seen | {key})


def message_to_plain(message: Any, seed: bool = False) -> dict:
    """Convert a message to plain dict/list/scalar values (bytes rendered as ints).

    ``seed=True`` collapses nested Header fields to the scalar ``'auto'`` so editor seeds
    prefill the "stamp at send time" magic instead of an expanded zeroed header.
    """
    return _plain_message(message, max_array=None, max_str=None, seed=seed)


def build_message(message_class: type, values: Any) -> tuple[Any, list[TimeSetter]]:
    """
    Build a checked message instance from ``yaml.safe_load`` output.

    Returns the message and the deferred time setters produced by the ``stamp: now`` /
    ``header: auto`` magic values (apply each with the current time before sending).
    Raises :class:`FieldError` on any mismatch.
    """
    if values is None:
        values = {}
    setters: list[TimeSetter] = []
    message = _build(message_class, values, '', setters)
    return message, setters


def to_truncated_yaml(
    message: Any,
    max_array: int = TRUNCATE_ARRAY_ELEMENTS,
    max_lines: int = TRUNCATE_RENDER_LINES,
) -> str:
    """Render a message as display YAML, truncating long arrays/strings and capping lines."""
    plain = _plain_message(message, max_array=max_array, max_str=TRUNCATE_STRING_CHARS)
    return _render_yaml_text(plain, max_lines, '(no fields)')


def to_filtered_yaml(
    message: Any,
    selected_paths: Any,
    max_array: int = TRUNCATE_ARRAY_ELEMENTS,
    max_lines: int = TRUNCATE_RENDER_LINES,
) -> str:
    """Like to_truncated_yaml, but only includes fields whose dotted path is in ``selected_paths``
    (or has a selected descendant, for nested/sequence-of-message fields)."""
    plain = _plain_message(
        message, max_array, TRUNCATE_STRING_CHARS, frozenset(selected_paths), ''
    )
    return _render_yaml_text(plain, max_lines, '(no fields)')


def _render_yaml_text(plain: dict, max_lines: int, empty_text: str) -> str:
    text = _dump_yaml(plain) if plain else empty_text
    lines = text.splitlines()
    if len(lines) > max_lines:
        hidden_count = len(lines) - max_lines
        lines = lines[:max_lines] + [f'… ({hidden_count} more lines)']
    return '\n'.join(lines)


def interface_label(message_class: type) -> str:
    """Best-effort 'pkg/msg/Type' label for a generated interface class."""
    module_parts = message_class.__module__.split('.')
    if len(module_parts) >= 2:
        return f'{module_parts[0]}/{module_parts[1]}/{message_class.__name__}'
    return message_class.__name__


def _checked_instance(message_class: type) -> Any:
    try:
        return message_class(check_fields=True)
    except TypeError:
        # Safety net for generated code without the kwarg; validation is then best-effort.
        return message_class()


def _build(message_class: type, values: Any, path: str, setters: list[TimeSetter]) -> Any:
    message = _checked_instance(message_class)
    if values is None:
        return message
    if not isinstance(values, dict):
        raise FieldError(
            path.rstrip('.'),
            f'expected a mapping for {interface_label(message_class)}, '
            f"got {type(values).__name__} '{values}'",
        )
    slots = get_message_slot_types(message)
    for field_name, field_value in values.items():
        field_path = f'{path}{field_name}'
        if field_name not in slots:
            raise FieldError(
                field_path, f"'{field_name}' is not a field of {interface_label(message_class)}"
            )
        slot = slots[field_name]
        current = getattr(message, field_name)
        qualified = f'{type(current).__module__}.{type(current).__name__}'
        if qualified == _HEADER_CLASS and field_value == 'auto':
            setters.append(functools.partial(setattr, current, 'stamp'))
            continue
        if qualified == _TIME_CLASS and field_value == 'now':
            setters.append(functools.partial(setattr, message, field_name))
            continue
        try:
            if isinstance(slot, AbstractNestedType):
                value = _build_sequence(current, slot, field_value, field_path, setters)
            elif hasattr(current, 'get_fields_and_field_types'):
                value = _build(type(current), field_value, f'{field_path}.', setters)
            elif isinstance(slot, BasicType) and slot.typename == 'octet':
                value = _byte_value(field_value, field_path)
            else:
                value = _coerce_primitive(current, field_value)
            setattr(message, field_name, value)
        except FieldError:
            raise
        except (AssertionError, ValueError, TypeError, OverflowError) as error:
            raise FieldError(field_path, str(error)) from error
    return message


def _build_sequence(
    current: Any,
    slot: AbstractNestedType,
    field_value: Any,
    field_path: str,
    setters: list[TimeSetter],
) -> Any:
    if isinstance(field_value, str) or not isinstance(field_value, (list, tuple)):
        raise FieldError(field_path, f'expected a list, got {type(field_value).__name__}')
    value_type = slot.value_type
    if isinstance(value_type, NamespacedType):
        element_class = import_message_from_namespaced_type(value_type)
        return [
            _build(element_class, item, f'{field_path}[{index}].', setters)
            for index, item in enumerate(field_value)
        ]
    if isinstance(value_type, BasicType) and value_type.typename == 'octet':
        return [
            _byte_value(item, f'{field_path}[{index}]') for index, item in enumerate(field_value)
        ]
    if isinstance(current, array.array):
        return array.array(current.typecode, field_value)
    if isinstance(current, numpy.ndarray):
        return _checked_numpy_array(current, field_value, field_path)
    return [
        _coerce_element(value_type, item, f'{field_path}[{index}]')
        for index, item in enumerate(field_value)
    ]


def _coerce_element(value_type: Any, item: Any, item_path: str) -> Any:
    try:
        if isinstance(value_type, (AbstractString, AbstractWString)):
            return item if isinstance(item, str) else str(item)
        if isinstance(value_type, BasicType):
            if value_type.typename == 'boolean':
                return bool(item)
            if value_type.typename in _FLOAT_TYPENAMES:
                return float(item)
            return int(item)
        return item
    except (ValueError, TypeError) as error:
        raise FieldError(item_path, str(error)) from error


def _checked_numpy_array(current: numpy.ndarray, field_value: Any, field_path: str) -> Any:
    """
    Validate every element before converting to a numpy array.

    numpy.array() silently truncates floats and wraps out-of-range ints (numpy < 2),
    and the generated setter only checks size.
    """
    checked = [
        _checked_numpy_element(current.dtype, item, f'{field_path}[{index}]')
        for index, item in enumerate(field_value)
    ]
    return numpy.array(checked, dtype=current.dtype)


def _checked_numpy_element(dtype: numpy.dtype, item: Any, item_path: str) -> Any:
    try:
        if dtype.kind == 'b':
            return bool(item)
        if dtype.kind in 'iu':
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise FieldError(item_path, f'expected an integer, got {item!r}')
            if isinstance(item, float):
                if not item.is_integer():
                    raise FieldError(item_path, f'expected an integer, got {item}')
                item = int(item)
            bounds = numpy.iinfo(dtype)
            if not bounds.min <= item <= bounds.max:
                raise FieldError(
                    item_path, f'must be an integer in [{bounds.min}, {bounds.max}], got {item}'
                )
            return item
        if dtype.kind == 'f':
            value = float(item)
            limit = float(numpy.finfo(dtype).max)
            if math.isfinite(value) and not -limit <= value <= limit:
                raise FieldError(item_path, f'must be a float in [{-limit}, {limit}], got {item}')
            return value
        return item
    except (TypeError, ValueError) as error:
        raise FieldError(item_path, str(error)) from error


def _coerce_primitive(current: Any, field_value: Any) -> Any:
    if type(field_value) is type(current):
        return field_value
    # Mirrors upstream set_message_fields: coerce through the current field's python type,
    # which also lets float fields accept ints and the strings 'nan'/'inf'.
    return type(current)(field_value)


def _byte_value(value: Any, path: str) -> bytes:
    if isinstance(value, bytes) and len(value) == 1:
        return value
    if isinstance(value, bool):
        raise FieldError(path, 'byte field must be an integer in [0, 255]')
    if isinstance(value, int):
        if not 0 <= value <= 255:
            raise FieldError(path, f'byte field must be an integer in [0, 255], got {value}')
        return bytes([value])
    if isinstance(value, str) and len(value) == 1 and ord(value) <= 255:
        return bytes([ord(value)])
    raise FieldError(path, f'byte field must be an integer in [0, 255], got {value!r}')


def _plain_message(
    message: Any,
    max_array: int | None,
    max_str: int | None,
    selected: frozenset[str] | None = None,
    path: str = '',
    seed: bool = False,
) -> dict:
    plain = {}
    for field_name, slot in zip(message.get_fields_and_field_types().keys(), message.SLOT_TYPES):
        child_path = schema_path(path, field_name)
        if selected is not None and not _field_included(child_path, selected):
            continue
        plain[field_name] = _plain_value(
            getattr(message, field_name), slot, max_array, max_str, selected, child_path, seed
        )
    return plain


def _field_included(path: str, selected: frozenset[str]) -> bool:
    return path in selected or any(candidate.startswith(f'{path}.') for candidate in selected)


def _plain_value(
    value: Any,
    slot: Any,
    max_array: int | None,
    max_str: int | None,
    selected: frozenset[str] | None = None,
    path: str = '',
    seed: bool = False,
) -> Any:
    if isinstance(slot, AbstractNestedType):
        total = len(value)
        truncated = max_array is not None and total > max_array
        items = value[:max_array] if truncated else value
        if isinstance(slot.value_type, BasicType) and slot.value_type.typename == 'octet':
            plain_items = [_byte_to_int(item) for item in items]
        else:
            # Sequence-of-message: reuse the same collapsed path for every element, so a
            # schema-level path like ``points.x`` filters each element uniformly.
            plain_items = [
                _plain_value(item, slot.value_type, max_array, max_str, selected, path, seed)
                for item in items
            ]
        if truncated:
            plain_items.append(f'… ({total} total)')
        return plain_items
    if isinstance(slot, BasicType) and slot.typename == 'octet':
        return _byte_to_int(value)
    if hasattr(value, 'get_fields_and_field_types'):
        qualified = f'{type(value).__module__}.{type(value).__name__}'
        if seed and qualified == _HEADER_CLASS:
            return 'auto'  # Prefill the "stamp at send time" magic instead of a zeroed header.
        return _plain_message(value, max_array, max_str, selected, path, seed)
    if isinstance(value, numpy.number):
        return value.item()
    if isinstance(value, str) and max_str is not None and len(value) > max_str:
        return value[:max_str] + f'… ({len(value)} chars total)'
    return value


def _byte_to_int(value: Any) -> int:
    return value[0] if isinstance(value, bytes) else int(value)


def _dump_yaml(plain: dict) -> str:
    return yaml.safe_dump(
        plain, sort_keys=False, default_flow_style=False, allow_unicode=True, width=2**31 - 1
    )


def _constants_comment(message_class: type) -> str:
    # Real IDL constants are primitive scalars; generated classes also expose internals like
    # _TYPE_SUPPORT and <FIELD>__DEFAULT (which str.isupper() matches), so filter those out.
    names = [
        name
        for name in dir(message_class)
        if name.isupper()
        and not name.startswith('_')
        and '__' not in name
        and isinstance(getattr(message_class, name), (bool, int, float, str))
    ]
    if not names or len(names) > MAX_CONSTANTS_IN_COMMENT:
        return ''
    pairs = [f'{name}={getattr(message_class, name)!r}' for name in names]
    lines = []
    line = '# constants:'
    for pair in pairs:
        if len(line) + len(pair) + 2 > 96:
            lines.append(line)
            line = '#  '
        line += f' {pair},'
    lines.append(line.rstrip(','))
    return '\n'.join(lines) + '\n'
