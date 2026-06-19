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

"""Pure unit tests for graph snapshot data structures and hidden-name filtering."""

from ros_tui.ros.graph import (
    EMPTY_GRAPH,
    GraphSnapshot,
    InterfaceEntry,
    is_builtin_service,
    is_hidden_name,
)


def test_hidden_names():
    assert is_hidden_name('/_foo')
    assert is_hidden_name('/ns/_private/x')
    assert is_hidden_name('/fibonacci/_action/feedback')
    assert is_hidden_name('/fibonacci/_action/send_goal')
    assert not is_hidden_name('/rosout')
    assert not is_hidden_name('/a/b')
    assert not is_hidden_name('/under_score_inside')


def test_builtin_services_are_filtered():
    assert is_builtin_service(('rcl_interfaces/srv/GetParameters',))
    assert is_builtin_service(('rcl_interfaces/srv/SetParametersAtomically',))
    assert is_builtin_service(('type_description_interfaces/srv/GetTypeDescription',))
    assert not is_builtin_service(('std_srvs/srv/Trigger',))
    assert not is_builtin_service(('turtlesim/srv/Spawn',))
    assert not is_builtin_service(())


def test_snapshot_equality_drives_diffing():
    entry = InterfaceEntry('/chatter', ('std_msgs/msg/String',))
    first = GraphSnapshot(1, (), (), (entry,))
    second = GraphSnapshot(2, (), (), (InterfaceEntry('/chatter', ('std_msgs/msg/String',)),))
    assert first.topics == second.topics  # Same content compares equal across versions.
    third = GraphSnapshot(3, (), (), ())
    assert first.topics != third.topics


def test_empty_graph_sentinel():
    assert EMPTY_GRAPH.version == 0
    assert EMPTY_GRAPH.topics == ()
