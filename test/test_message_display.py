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

"""message_to_display: what an echo or a feedback shows, with long arrays and strings cut."""

import array
import time

from ros_tui.ros.message_yaml import import_type, message_to_display


def test_array_over_limit_truncated_with_total():
    message = import_type('msg', 'std_msgs/msg/UInt8MultiArray')(data=list(range(100)))
    shown = message_to_display(message)['data']
    assert len(shown) == 17
    assert shown[:3] == [0, 1, 2]
    assert shown[16] == '… (100 total)'


def test_array_at_limit_not_truncated():
    message = import_type('msg', 'std_msgs/msg/UInt8MultiArray')(data=list(range(16)))
    assert message_to_display(message)['data'] == list(range(16))


def test_nested_message_arrays_truncated():
    point_class = import_type('msg', 'geometry_msgs/msg/Point32')
    message = import_type('msg', 'geometry_msgs/msg/Polygon')(points=[point_class(x=float(i)) for i in range(40)])
    shown = message_to_display(message)['points']
    assert len(shown) == 17
    assert shown[0] == {'x': 0.0, 'y': 0.0, 'z': 0.0}
    assert shown[16] == '… (40 total)'


def test_long_string_truncated():
    message = import_type('msg', 'std_msgs/msg/String')(data='x' * 1000)
    assert message_to_display(message)['data'].endswith('… (1000 chars total)')


def test_megabyte_blob_converts_fast():
    message = import_type('msg', 'sensor_msgs/msg/PointCloud2')()
    message.data = array.array('B', bytes(1_000_000))
    start = time.monotonic()
    shown = message_to_display(message)
    assert time.monotonic() - start < 0.5
    assert shown['data'][-1] == '… (1000000 total)'


def test_no_fields_message_is_empty():
    assert message_to_display(import_type('srv', 'std_srvs/srv/Trigger').Request()) == {}
