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

"""Pure unit tests for the truncating display renderer."""

import array
import time

import yaml
from ros_tui.ros.message_yaml import import_type, to_filtered_yaml, to_truncated_yaml


def test_array_over_limit_truncated_with_total():
    multi_array_class = import_type('msg', 'std_msgs/msg/UInt8MultiArray')
    message = multi_array_class()
    message.data = list(range(100))
    rendered = yaml.safe_load(to_truncated_yaml(message))
    assert len(rendered['data']) == 17
    assert rendered['data'][:3] == [0, 1, 2]
    assert rendered['data'][16] == '… (100 total)'


def test_array_at_limit_not_truncated():
    multi_array_class = import_type('msg', 'std_msgs/msg/UInt8MultiArray')
    message = multi_array_class()
    message.data = list(range(16))
    rendered = yaml.safe_load(to_truncated_yaml(message))
    assert rendered['data'] == list(range(16))


def test_nested_message_arrays_truncated():
    polygon_class = import_type('msg', 'geometry_msgs/msg/Polygon')
    point_class = import_type('msg', 'geometry_msgs/msg/Point32')
    message = polygon_class()
    message.points = [point_class(x=float(index)) for index in range(40)]
    rendered = yaml.safe_load(to_truncated_yaml(message))
    assert len(rendered['points']) == 17
    assert rendered['points'][0] == {'x': 0.0, 'y': 0.0, 'z': 0.0}
    assert rendered['points'][16] == '… (40 total)'


def test_line_cap_appends_hidden_count():
    joint_state_class = import_type('msg', 'sensor_msgs/msg/JointState')
    message = joint_state_class()
    message.name = [f'joint_{index}' for index in range(10)]
    rendered = to_truncated_yaml(message, max_lines=5)
    lines = rendered.splitlines()
    assert len(lines) == 6
    assert 'more lines' in lines[-1]


def test_long_string_truncated():
    string_class = import_type('msg', 'std_msgs/msg/String')
    message = string_class(data='x' * 1000)
    rendered = to_truncated_yaml(message)
    assert '(1000 chars total)' in rendered


def test_megabyte_blob_renders_fast():
    cloud_class = import_type('msg', 'sensor_msgs/msg/PointCloud2')
    message = cloud_class()
    message.data = array.array('B', bytes(1_000_000))
    start = time.monotonic()
    rendered = to_truncated_yaml(message)
    elapsed = time.monotonic() - start
    assert elapsed < 0.5
    assert '(1000000 total)' in rendered


def test_no_fields_message_renders_placeholder():
    trigger = import_type('srv', 'std_srvs/srv/Trigger')
    assert to_truncated_yaml(trigger.Request()) == '(no fields)'


def test_filtered_keeps_only_selected_scalar():
    point_class = import_type('msg', 'geometry_msgs/msg/Point')
    message = point_class(x=1.0, y=2.0, z=3.0)
    rendered = yaml.safe_load(to_filtered_yaml(message, {'x'}))
    assert rendered == {'x': 1.0}


def test_filtered_keeps_nested_path():
    pose_class = import_type('msg', 'geometry_msgs/msg/PoseStamped')
    message = pose_class()
    message.pose.position.x = 5.0
    rendered = yaml.safe_load(to_filtered_yaml(message, {'pose.position.x'}))
    assert rendered == {'pose': {'position': {'x': 5.0}}}


def test_filtered_sequence_of_message_applies_subpath_per_element():
    polygon_class = import_type('msg', 'geometry_msgs/msg/Polygon')
    point_class = import_type('msg', 'geometry_msgs/msg/Point32')
    message = polygon_class()
    message.points = [point_class(x=float(index), y=9.0) for index in range(3)]
    rendered = yaml.safe_load(to_filtered_yaml(message, {'points.x'}))
    assert rendered == {'points': [{'x': 0.0}, {'x': 1.0}, {'x': 2.0}]}


def test_filtered_all_leaves_matches_truncated():
    pose_class = import_type('msg', 'geometry_msgs/msg/PoseStamped')
    message = pose_class()
    all_paths = {
        'header.stamp.sec',
        'header.stamp.nanosec',
        'header.frame_id',
        'pose.position.x',
        'pose.position.y',
        'pose.position.z',
        'pose.orientation.x',
        'pose.orientation.y',
        'pose.orientation.z',
        'pose.orientation.w',
    }
    assert to_filtered_yaml(message, all_paths) == to_truncated_yaml(message)


def test_filtered_array_still_truncated():
    multi_array_class = import_type('msg', 'std_msgs/msg/UInt8MultiArray')
    message = multi_array_class()
    message.data = list(range(100))
    rendered = yaml.safe_load(to_filtered_yaml(message, {'data'}))
    assert 'layout' not in rendered
    assert len(rendered['data']) == 17
    assert rendered['data'][16] == '… (100 total)'
