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
A node's parameters: their type labels, and the rcl_interfaces ParameterValue they travel as.

A parameter is a `Param(name, type, value)`. Its type is one of the labels in `TYPES` (bool,
int, double, string and their arrays), or `UNKNOWN` with value None for a type that can't be read.
A value is plain Python: bool, int, float, str or a list of them; a byte[] is a list of ints in
0..255, never the bytes elements rcl holds it as.

`read_parameters` turns the values a node answered with into Params; `parameter_value` builds the
ParameterValue to set one, by the type the parameter was declared with, never by what the Python
value looks like: whole numbers for a double are sent as doubles, and an empty list is sent as the
array type it was declared as. `checked` is its check alone, which the UI runs on a typed value.

rcl_interfaces is imported only when a value is read or built, so the UI can import this module
for `Param` and the labels without loading ROS.
"""

import functools
from typing import Any, NamedTuple

BOOL = 'bool'
INT = 'int'
DOUBLE = 'double'
STRING = 'string'
BYTES = 'byte[]'
UNKNOWN = '?'  # A type the bridge can't read; such a parameter is shown but can't be set.

# label -> (rcl_interfaces ParameterType constant, ParameterValue field, Python type of a value or
# of an array's element).
_FIELDS = {
    BOOL: ('PARAMETER_BOOL', 'bool_value', bool),
    INT: ('PARAMETER_INTEGER', 'integer_value', int),
    DOUBLE: ('PARAMETER_DOUBLE', 'double_value', float),
    STRING: ('PARAMETER_STRING', 'string_value', str),
    BYTES: ('PARAMETER_BYTE_ARRAY', 'byte_array_value', int),
    'bool[]': ('PARAMETER_BOOL_ARRAY', 'bool_array_value', bool),
    'int[]': ('PARAMETER_INTEGER_ARRAY', 'integer_array_value', int),
    'double[]': ('PARAMETER_DOUBLE_ARRAY', 'double_array_value', float),
    'string[]': ('PARAMETER_STRING_ARRAY', 'string_array_value', str),
}
TYPES = tuple(_FIELDS)


class Param(NamedTuple):
    name: str
    type: str  # One of TYPES, or UNKNOWN.
    value: Any  # None when the type is UNKNOWN.


@functools.lru_cache(maxsize=1)
def _labels() -> dict[int, str]:
    """ParameterType number -> label."""
    from rcl_interfaces.msg import ParameterType  # noqa: PLC0415
    return {getattr(ParameterType, constant): label for label, (constant, _, _) in _FIELDS.items()}


def read_parameters(names: list[str], values: list[Any]) -> list[Param]:
    """The Params for `names` and the ParameterValues a node's get_parameters answered with."""
    labels = _labels()
    params = []
    for name, raw in zip(names, values):
        label = labels.get(raw.type, UNKNOWN)
        value = None if label == UNKNOWN else getattr(raw, _FIELDS[label][1])
        if hasattr(value, 'tolist'):  # Number arrays come back as array.array / numpy.
            value = value.tolist()
        elif label == BYTES:  # A list of one-byte bytes.
            value = [item[0] for item in value]
        params.append(Param(name, label, value))
    return params


_INT64 = range(-2**63, 2**63)
_BYTE = range(256)


def _coerced(item: Any, element: type, whole: range) -> Any:
    """One value (or array element) as a field of Python type `element` holds it; ValueError if it
    can't. A whole number for a double becomes a float, and an int must be in `whole`."""
    if element is float and type(item) is int:
        try:
            return float(item)
        except OverflowError:
            raise ValueError from None
    if type(item) is not element or (element is int and item not in whole):
        raise ValueError
    return item


def checked(value: Any, label: str) -> Any:
    """`value` as a parameter declared as `label` holds it: whole numbers for a double as floats.
    No ROS import, so the UI checks a typed value with it.

    Raises ValueError for a label not in TYPES, or a value that type can't hold: a str for an int,
    a list for a scalar, an int in a string[] (bools are not ints here), an int outside int64, a
    byte outside 0..255.
    """
    if label not in _FIELDS:
        raise ValueError(f'cannot set a parameter of type {label}')
    element = _FIELDS[label][2]
    whole = _BYTE if label == BYTES else _INT64
    try:
        if not label.endswith('[]'):
            return _coerced(value, element, whole)
        if type(value) is not list:
            raise ValueError
        return [_coerced(item, element, whole) for item in value]
    except ValueError:
        raise ValueError(f'{value!r} does not fit type {label}') from None


def parameter_value(value: Any, label: str) -> Any:
    """The rcl_interfaces ParameterValue that sets a parameter declared as `label` to `value`.
    ValueError as `checked`."""
    built = checked(value, label)
    if label == BYTES:
        built = [bytes([item]) for item in built]  # As rcl holds it: a list of ints aborts.
    constant, field, _ = _FIELDS[label]
    from rcl_interfaces.msg import ParameterType, ParameterValue  # noqa: PLC0415
    parameter = ParameterValue(type=getattr(ParameterType, constant))
    setattr(parameter, field, built)
    return parameter
