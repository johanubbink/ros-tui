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

"""Immutable snapshots of the ROS graph (actions, services, topics, nodes)."""

from dataclasses import dataclass
from typing import Any

from rclpy.action import (
    get_action_client_names_and_types_by_node,
    get_action_names_and_types,
    get_action_server_names_and_types_by_node,
)


@dataclass(frozen=True)
class InterfaceEntry:
    name: str
    types: tuple[str, ...]  # Usually exactly one; extras are shown but types[0] is used.


@dataclass(frozen=True)
class GraphSnapshot:
    version: int  # Bumps only on real change; 0 is the empty pre-discovery sentinel.
    actions: tuple[InterfaceEntry, ...]
    services: tuple[InterfaceEntry, ...]
    topics: tuple[InterfaceEntry, ...]
    nodes: tuple[InterfaceEntry, ...]


@dataclass(frozen=True)
class NodeInfo:
    """One node's graph endpoints, à la `ros2 node info`."""

    node_name: str  # Full name, e.g. '/ns/talker'.
    publishers: tuple[InterfaceEntry, ...]
    subscribers: tuple[InterfaceEntry, ...]
    service_servers: tuple[InterfaceEntry, ...]
    service_clients: tuple[InterfaceEntry, ...]
    action_servers: tuple[InterfaceEntry, ...]
    action_clients: tuple[InterfaceEntry, ...]


EMPTY_GRAPH = GraphSnapshot(version=0, actions=(), services=(), topics=(), nodes=())

# Services rclpy auto-creates on every node for parameter handling and type
# introspection. The Nodes tab already exposes these, so the Services tab
# hides them to cut noise. Matched by type (package/srv/TypeName) so node
# naming is irrelevant.
BUILTIN_SERVICE_TYPES = frozenset({
    'rcl_interfaces/srv/DescribeParameters',
    'rcl_interfaces/srv/GetParameters',
    'rcl_interfaces/srv/GetParameterTypes',
    'rcl_interfaces/srv/ListParameters',
    'rcl_interfaces/srv/SetParameters',
    'rcl_interfaces/srv/SetParametersAtomically',
    'type_description_interfaces/srv/GetTypeDescription',
})


def is_hidden_name(name: str) -> bool:
    """ROS hides names with any '_'-prefixed token, e.g. /_x or /foo/_action/feedback."""
    return any(token.startswith('_') for token in name.split('/') if token)


def is_builtin_service(types) -> bool:
    """True when every advertised type is an auto-created node service."""
    return bool(types) and all(t in BUILTIN_SERVICE_TYPES for t in types)


def build_snapshot(node: Any, version: int) -> GraphSnapshot:
    """Query the graph through ``node``. Must be called on the thread spinning the node."""

    def entries(name_type_pairs, *, skip=None) -> tuple[InterfaceEntry, ...]:
        return tuple(
            InterfaceEntry(name, tuple(types))
            for name, types in sorted(name_type_pairs)
            if not is_hidden_name(name) and not (skip and skip(types))
        )

    def node_entries() -> tuple[InterfaceEntry, ...]:
        # ROS allows duplicate node names, and get_node_names_and_namespaces() can
        # report the same node twice during discovery; dedup so each full name is
        # listed once (downstream Option/row keys assume names are unique).
        # Skip our own bridge node: it is the tool's introspection plumbing, not a
        # node the user came to inspect (and its endpoints churn as the app is used).
        own = f'{node.get_namespace().rstrip("/")}/{node.get_name()}'
        result = []
        seen = set()
        for name, namespace in sorted(node.get_node_names_and_namespaces()):
            if name.startswith('_'):
                continue
            full = f'{namespace.rstrip("/")}/{name}'
            if full == own or full in seen:
                continue
            seen.add(full)
            result.append(InterfaceEntry(full, (namespace,)))
        return tuple(result)

    return GraphSnapshot(
        version=version,
        actions=entries(get_action_names_and_types(node)),
        services=entries(node.get_service_names_and_types(), skip=is_builtin_service),
        topics=entries(node.get_topic_names_and_types()),
        nodes=node_entries(),
    )


def split_node_name(full_name: str) -> tuple[str, str]:
    """'/ns/talker' -> ('talker', '/ns'); '/talker' -> ('talker', '/')."""
    namespace, _, name = full_name.rpartition('/')
    return name, (namespace or '/')


def build_node_info(node: Any, full_name: str) -> NodeInfo:
    """Introspect ``full_name``'s endpoints via ``node``. Call on the node's spin thread.

    Hidden names (the action's internal ``/foo/_action/*`` topics & services) and the node's
    auto-created parameter services are dropped, matching what the Services/Nodes tabs show —
    so a jump from here always lands on an entity the destination tab actually lists.
    """
    name, namespace = split_node_name(full_name)

    def entries(name_type_pairs, *, skip=None) -> tuple[InterfaceEntry, ...]:
        return tuple(
            InterfaceEntry(entry_name, tuple(types))
            for entry_name, types in sorted(name_type_pairs)
            if not is_hidden_name(entry_name) and not (skip and skip(types))
        )

    return NodeInfo(
        node_name=full_name,
        publishers=entries(node.get_publisher_names_and_types_by_node(name, namespace)),
        subscribers=entries(node.get_subscriber_names_and_types_by_node(name, namespace)),
        service_servers=entries(
            node.get_service_names_and_types_by_node(name, namespace), skip=is_builtin_service
        ),
        service_clients=entries(
            node.get_client_names_and_types_by_node(name, namespace), skip=is_builtin_service
        ),
        action_servers=entries(
            get_action_server_names_and_types_by_node(node, name, namespace)
        ),
        action_clients=entries(
            get_action_client_names_and_types_by_node(node, name, namespace)
        ),
    )
