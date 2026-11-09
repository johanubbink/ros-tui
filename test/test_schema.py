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

"""Type labels and field paths (ros_tui/ros/schema.py): pure strings, no ROS import."""

import subprocess
import sys

from ros_tui.ros.schema import array_info, parse_path, path_text, short_type


def test_paths_and_hints():
    assert path_text(('points', 1, 'x')) == 'points[1].x' and parse_path('points[1].x') == ('points', 1, 'x')
    assert [short_type(label) for label in ('int64', 'geometry_msgs/Point', 'double[9]',
                                            'sequence<geometry_msgs/Point32>', 'sequence<double, 3>')] == [
        'int64', 'Point', 'double[9]', 'Point32[]', 'double[<=3]']
    assert array_info('sequence<string<=5, 3>') == ('string<=5', None, 3)


def test_importing_it_loads_no_ros():
    """The UI reads labels and paths with it: neither rosidl nor rclpy loads."""
    code = ('import sys, ros_tui.ros.schema; '
            'print(sorted(m for m in sys.modules if m.split(".")[0].startswith(("rosidl", "rclpy"))))')
    assert subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                          check=True).stdout.strip() == '[]'
