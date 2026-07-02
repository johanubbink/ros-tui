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

"""Action lifecycle events emitted by the bridge (always on the ROS thread)."""

import enum
from dataclasses import dataclass
from typing import Any


class ActionEventKind(enum.Enum):
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    FEEDBACK = 'feedback'
    RESULT = 'result'
    CANCEL_ACCEPTED = 'cancel_accepted'
    CANCEL_REJECTED = 'cancel_rejected'
    ERROR = 'error'


@dataclass(frozen=True)
class ActionEvent:
    action_name: str
    kind: ActionEventKind
    payload: Any | None = None  # Feedback msg, Result msg, or an error string.
    status: int | None = None  # action_msgs GoalStatus.* — set for RESULT events.


# The standardized action_msgs/msg/GoalStatus.STATUS_* constants, hardcoded so this module
# imports without ROS (it is pulled in by the UI). These values are fixed by the ROS 2 action
# protocol and never change.
_STATUS_NAMES = {
    0: 'UNKNOWN',
    1: 'ACCEPTED',
    2: 'EXECUTING',
    3: 'CANCELING',
    4: 'SUCCEEDED',
    5: 'CANCELED',
    6: 'ABORTED',
}


def goal_status_name(status: int | None) -> str:
    return _STATUS_NAMES.get(status, f'UNKNOWN({status})')
