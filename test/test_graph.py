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
    build_node_info,
    build_snapshot,
    is_builtin_service,
    is_hidden_name,
    split_node_name,
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
    first = GraphSnapshot(1, (), (), (entry,), ())
    second = GraphSnapshot(2, (), (), (InterfaceEntry('/chatter', ('std_msgs/msg/String',)),), ())
    assert first.topics == second.topics  # Same content compares equal across versions.
    third = GraphSnapshot(3, (), (), (), ())
    assert first.topics != third.topics


def test_empty_graph_sentinel():
    assert EMPTY_GRAPH.version == 0
    assert EMPTY_GRAPH.topics == ()


class _StubNode:
    """Minimal node exposing only the graph-query methods build_snapshot calls."""

    def __init__(self, node_names_and_namespaces):
        self._nodes = node_names_and_namespaces

    def get_node_names_and_namespaces(self):
        return self._nodes

    def get_service_names_and_types(self):
        return []

    def get_topic_names_and_types(self):
        return []


def test_duplicate_node_names_are_deduped(monkeypatch):
    # ROS can report the same node twice; the snapshot must list it once so
    # downstream Option ids stay unique (regression: textual DuplicateID crash).
    monkeypatch.setattr('ros_tui.ros.graph.get_action_names_and_types', lambda node: [])
    node = _StubNode([('node_a', '/'), ('node_a', '/')])
    snapshot = build_snapshot(node, 1)
    assert len(snapshot.nodes) == 1
    assert snapshot.nodes[0].name == '/node_a'


def test_split_node_name():
    assert split_node_name('/ns/talker') == ('talker', '/ns')
    assert split_node_name('/talker') == ('talker', '/')
    assert split_node_name('/deep/ns/talker') == ('talker', '/deep/ns')


class _IntrospectNode:
    """Node exposing the per-node graph queries build_node_info calls."""

    def __init__(self, by_node):
        self._by_node = by_node  # {method_name: [(name, [types]), ...]}

    def _get(self, key, node_name, namespace):
        return list(self._by_node.get(key, []))

    def get_publisher_names_and_types_by_node(self, n, ns):
        return self._get('pub', n, ns)

    def get_subscriber_names_and_types_by_node(self, n, ns):
        return self._get('sub', n, ns)

    def get_service_names_and_types_by_node(self, n, ns):
        return self._get('srv', n, ns)

    def get_client_names_and_types_by_node(self, n, ns):
        return self._get('cli', n, ns)


def test_build_node_info_filters_and_maps(monkeypatch):
    node = _IntrospectNode({
        'pub': [
            ('/chatter', ['std_msgs/msg/String']),
            ('/fibonacci/_action/feedback', ['example_interfaces/action/Fibonacci_FeedbackMessage']),
        ],
        'sub': [('/inbox', ['std_msgs/msg/String'])],
        'srv': [
            ('/add_two_ints', ['example_interfaces/srv/AddTwoInts']),
            ('/talker/get_parameters', ['rcl_interfaces/srv/GetParameters']),
        ],
        'cli': [('/talker/set_parameters', ['rcl_interfaces/srv/SetParameters'])],
    })
    monkeypatch.setattr(
        'ros_tui.ros.graph.get_action_server_names_and_types_by_node',
        lambda node, n, ns: [('/fibonacci', ['example_interfaces/action/Fibonacci'])],
    )
    monkeypatch.setattr(
        'ros_tui.ros.graph.get_action_client_names_and_types_by_node',
        lambda node, n, ns: [],
    )

    info = build_node_info(node, '/talker')

    assert info.node_name == '/talker'
    # Hidden /_action/* publisher dropped; real publisher kept.
    assert [e.name for e in info.publishers] == ['/chatter']
    assert info.publishers[0].types == ('std_msgs/msg/String',)
    assert [e.name for e in info.subscribers] == ['/inbox']
    # Built-in parameter services dropped from both server and client lists.
    assert [e.name for e in info.service_servers] == ['/add_two_ints']
    assert info.service_clients == ()
    assert [e.name for e in info.action_servers] == ['/fibonacci']
    assert info.action_clients == ()
