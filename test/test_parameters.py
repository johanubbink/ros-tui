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

"""A parameter's ParameterValue is built by its declared type, and read back to the same Param."""

import subprocess
import sys

import pytest
from rcl_interfaces.msg import ParameterType, ParameterValue
from ros_tui.ros.parameters import TYPES, UNKNOWN, Param, parameter_value, read_parameters


@pytest.mark.parametrize('label, value, read_back', [
    ('bool', True, True),
    ('int', 42, 42),
    ('double', 2.5, 2.5),
    ('double', 5, 5.0),  # A whole number for a double is sent as a double.
    ('string', 'map', 'map'),
    ('string', '', ''),
    ('bool[]', [True, False], [True, False]),
    ('int[]', [1, 2], [1, 2]),
    ('double[]', [1, 2.5], [1.0, 2.5]),
    ('string[]', ['a', 'b'], ['a', 'b']),
    ('byte[]', [1, 255], [1, 255]),  # A byte array is read and written as ints, not bytes.
    ('int', 2**63 - 1, 2**63 - 1), ('int[]', [-2**63], [-2**63]),
] + [(label, [], []) for label in TYPES if label.endswith('[]')])  # An empty list keeps its type.
def test_a_value_round_trips_as_its_declared_type(label, value, read_back):
    built = parameter_value(value, label)
    param = read_parameters(['p'], [built])[0]
    assert param == Param('p', label, read_back)
    assert type(param.value) is type(read_back)


def test_the_type_sent_is_the_declared_one_not_the_value_s():
    assert parameter_value([1, 2], 'double[]').type == ParameterType.PARAMETER_DOUBLE_ARRAY
    assert parameter_value([], 'string[]').type == ParameterType.PARAMETER_STRING_ARRAY


def test_a_byte_array_is_sent_as_one_byte_bytes():
    # rclpy aborts the process, without raising, when it sends ints as a byte array.
    assert list(parameter_value([1, 255], 'byte[]').byte_array_value) == [b'\x01', b'\xff']


@pytest.mark.parametrize('label, value', [
    ('int', 'ten'), ('int', True), ('int', 2.5), ('bool', 'yes'), ('double', [1.0]), ('string[]', [1]),
    ('int[]', 3), (UNKNOWN, 1), ('float', 1.0),
    ('byte[]', [256]), ('byte[]', [-1]), ('byte[]', [b'\x07']), ('byte[]', [True]),
    ('int', 2**63), ('int[]', [-2**63 - 1]), ('double', 10**400), ('double[]', [10**400]),
])
def test_a_value_the_type_cannot_hold_raises(label, value):
    with pytest.raises(ValueError):
        parameter_value(value, label)


def test_a_type_that_cannot_be_read_is_unknown_with_no_value():
    not_set = ParameterValue(type=ParameterType.PARAMETER_NOT_SET)
    assert read_parameters(['p', 'q'], [not_set, parameter_value(1, 'int')]) == [
        Param('p', UNKNOWN, None), Param('q', 'int', 1),
    ]


def test_importing_it_loads_no_ros_interfaces():
    """The UI imports it for Param and the labels: rcl_interfaces loads only to read or build."""
    code = 'import sys, ros_tui.ros.parameters; print("rcl_interfaces" in sys.modules)'
    assert subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                          check=True).stdout.strip() == 'False'
