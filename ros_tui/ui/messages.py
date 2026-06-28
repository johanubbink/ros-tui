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
Textual messages crossing the ROS-thread -> UI-thread boundary.

``post_message`` is the only channel the bridge callbacks are allowed to use.
"""

from typing import Any

from textual.message import Message

from ros_tui.ros.events import ActionEvent
from ros_tui.ros.graph import GraphSnapshot, InterfaceEntry


class GraphUpdated(Message):
    def __init__(self, snapshot: GraphSnapshot):
        super().__init__()
        self.snapshot = snapshot


class PrototypeReady(Message):
    """A type was imported and its default YAML seeded (or failed) in a thread worker."""

    def __init__(self, entry_name: str, type_name: str, seed_text: str, error: str):
        super().__init__()
        self.entry_name = entry_name
        self.type_name = type_name
        self.seed_text = seed_text
        self.error = error


class ServiceCompleted(Message):
    def __init__(self, service_name: str, response: Any, error: str | None, elapsed_ms: float):
        super().__init__()
        self.service_name = service_name
        self.response = response
        self.error = error
        self.elapsed_ms = elapsed_ms


class ActionEventMessage(Message):
    def __init__(self, event: ActionEvent):
        super().__init__()
        self.event = event


class PublishCompleted(Message):
    """Outcome of a publish-once / start-rate / stop-rate command on the ROS thread."""

    def __init__(self, topic_name: str, label: str, error: str | None):
        super().__init__()
        self.topic_name = topic_name
        self.label = label
        self.error = error


class NodeParametersReady(Message):
    """Parameter list+values fetched (or failed) from a node."""

    def __init__(self, node_name: str, params: list | None, error: str | None):
        super().__init__()
        self.node_name = node_name
        self.params = params
        self.error = error


class ParameterSetCompleted(Message):
    """Outcome of a set_node_parameter call."""

    def __init__(self, node_name: str, param_name: str, error: str | None):
        super().__init__()
        self.node_name = node_name
        self.param_name = param_name
        self.error = error


class NodeInfoReady(Message):
    """A node's interface endpoints were introspected (or failed) on the ROS thread."""

    def __init__(self, node_name: str, info: Any, error: str | None):
        super().__init__()
        self.node_name = node_name
        self.info = info  # ros_tui.ros.graph.NodeInfo when error is None.
        self.error = error


class NavigateToEntity(Message):
    """Ask the app to switch to ``tab_id`` and select ``entry`` there."""

    def __init__(self, tab_id: str, entry: InterfaceEntry):
        super().__init__()
        self.tab_id = tab_id  # 'topics' | 'services' | 'actions'
        self.entry = entry
