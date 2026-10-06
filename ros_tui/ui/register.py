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

"""The y / p register (the design's S.reg): one copied message, with its type.

Pure Python. `y` copies a message as exact plain values: an echo's latest (or frozen) message, or
what an editor holds (a topic's message, a service's request, an action's goal). `p` pastes it
into an editor only when it is the same type in the same role, so a String never lands in a
PoseStamped and a service's request never in its response. The entries do the copying and the
pasting (entries/message.py, entries/topic.py); NavState holds the one register, app-wide.
"""

import copy
from dataclasses import dataclass

# An entry kind's editor -> the role of the message it holds.
ROLES = {'topics': 'message', 'services': 'request', 'actions': 'goal'}


def type_label(type_name: str, role: str) -> str:
    """How a copied type reads: 'String' for a topic's message, 'AddTwoInts request' otherwise."""
    short = type_name.rsplit('/', 1)[-1]
    return short if role == 'message' else f'{short} {role}'


@dataclass(frozen=True)
class Register:
    type: str  # The full type: 'std_msgs/msg/String', 'example_interfaces/srv/AddTwoInts'.
    role: str  # 'message', 'request' or 'goal'.
    source: str  # The entry it was copied from: '/chatter'.
    values: dict  # The message as exact plain values (never the display-cut ones).

    @staticmethod
    def of(type_name: str, role: str, source: str, values: dict) -> 'Register':
        """A copy of `values`, so later edits in the editor it came from don't change it."""
        return Register(type_name, role, source, copy.deepcopy(values))

    @property
    def label(self) -> str:
        return type_label(self.type, self.role)

    def chip(self) -> str:
        """The top bar's chip: 'copied: String from /chatter · p pastes'."""
        return f'copied: {self.label} from {self.source} · p pastes'

    def mismatch(self, type_name: str, role: str) -> str:
        """Why it can't be pasted where a `type_name` `role` is needed, or '' when it can."""
        if (self.type, self.role) == (type_name, role):
            return ''
        return f'copied a {self.label}, this needs a {type_label(type_name, role)}'
