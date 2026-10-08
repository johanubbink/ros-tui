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

"""The entry kinds by catalogue kind, and the factory NavState makes each tab's entry with.

Bridge results reach an entry through `post`, which runs a function on the UI thread, and slow
imports run through `work`, in a worker thread (see `RosTuiApp`).
"""

from typing import Any, Callable

from ros_tui.ui.entries.action import ActionEntry
from ros_tui.ui.entries.base import Context, Entry, Post, Tab, Work
from ros_tui.ui.entries.node import NodeEntry
from ros_tui.ui.entries.service import ServiceEntry
from ros_tui.ui.entries.topic import TopicEntry

KINDS: dict[str, type[Entry]] = {
    'topics': TopicEntry, 'services': ServiceEntry, 'actions': ActionEntry, 'nodes': NodeEntry}


def entry_factory(bridge: Any, post: Post | None = None, work: Work | None = None) -> Callable[[Tab], Entry]:
    """NavState's `new_entry` in the app: each tab's entry of its kind, all over one `Context`."""
    ctx = Context(bridge, post, work)
    return lambda tab: KINDS.get(tab.kind, Entry)(tab, ctx)
