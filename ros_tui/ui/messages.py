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

from typing import Callable

from textual.message import Message

from ros_tui.ros.graph import GraphSnapshot


class GraphUpdated(Message):
    def __init__(self, snapshot: GraphSnapshot):
        super().__init__()
        self.snapshot = snapshot


class PublisherCount(Message):
    """How many publishers a topic has, asked for each topic when the graph changes."""

    def __init__(self, topic_name: str, count: int):
        super().__init__()
        self.topic_name = topic_name
        self.count = count


class UiCall(Message):
    """A bridge answer for an entry provider: `fn` runs on the UI thread, then the views redraw."""

    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self.fn = fn
