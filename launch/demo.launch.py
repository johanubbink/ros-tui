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

"""Launch a set of example servers for exploring ros_tui.

    ros2 launch ros_tui demo.launch.py                  # headless demo servers
    ros2 launch ros_tui demo.launch.py turtlesim:=true  # also start turtlesim (needs a display)

Then, in another terminal:

    ros2 run ros_tui ros_tui

Extra example nodes can be appended to the returned list.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'turtlesim',
            default_value='false',
            description='Also launch turtlesim_node (opens a GUI window — requires an X display).',
        ),
        Node(
            package='ros_tui',
            executable='demo_servers',
            name='ros_tui_demo_servers',
            output='screen',
            emulate_tty=True,
        ),
        Node(
            package='turtlesim',
            executable='turtlesim_node',
            name='turtlesim',
            output='screen',
            condition=IfCondition(LaunchConfiguration('turtlesim')),
        ),
    ])
