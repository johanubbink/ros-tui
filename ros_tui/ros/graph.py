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

from rclpy.action import get_action_names_and_types


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


EMPTY_GRAPH = GraphSnapshot(version=0, actions=(), services=(), topics=(), nodes=())

# Services rclpy auto-creates on every node for parameter handling and type
# introspection. The Params tab already exposes these, so the Services tab
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
        result = []
        for name, namespace in sorted(node.get_node_names_and_namespaces()):
            if name.startswith('_'):
                continue
            full = f'{namespace.rstrip("/")}/{name}'
            result.append(InterfaceEntry(full, (namespace,)))
        return tuple(result)

    return GraphSnapshot(
        version=version,
        actions=entries(get_action_names_and_types(node)),
        services=entries(node.get_service_names_and_types(), skip=is_builtin_service),
        topics=entries(node.get_topic_names_and_types()),
        nodes=node_entries(),
    )
