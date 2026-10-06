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

"""Bounded, thread-safe hand-off of subscribed messages from the ROS thread to the UI."""

import threading
import time
from collections import deque
from typing import Any, Callable

from ros_tui.constants import ECHO_BUFFER_MAXLEN, ECHO_HZ_WINDOW

_RATE_STALE_S = 2.0


class EchoBuffer:
    """push() on the ROS thread, drain() on the UI thread; overflow drops oldest.

    ``clock`` times the arrivals for the rate (the entries pass the bridge's ``now()``, so a fake
    clock gives repeatable rates)."""

    def __init__(self, maxlen: int = ECHO_BUFFER_MAXLEN, hz_window: int = ECHO_HZ_WINDOW,
                 clock: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self._messages: deque[Any] = deque(maxlen=maxlen)
        self._arrival_stamps: deque[float] = deque(maxlen=hz_window)
        self._received_total = 0
        self._delivered_total = 0

    def push(self, message: Any) -> None:
        with self._lock:
            self._messages.append(message)
            self._received_total += 1
            self._arrival_stamps.append(self._clock())

    def pending(self) -> int:
        """How many messages the next drain() would return."""
        with self._lock:
            return len(self._messages)

    def drain(self) -> tuple[list[Any], int, int, float]:
        """Return (pending messages, received total, dropped total, receive rate in Hz)."""
        with self._lock:
            messages = list(self._messages)
            self._messages.clear()
            self._delivered_total += len(messages)
            dropped_total = self._received_total - self._delivered_total
            return messages, self._received_total, dropped_total, self._rate_locked()

    def _rate_locked(self) -> float:
        if len(self._arrival_stamps) < 2:
            return 0.0
        now = self._clock()
        if now - self._arrival_stamps[-1] > _RATE_STALE_S:
            return 0.0
        span = self._arrival_stamps[-1] - self._arrival_stamps[0]
        if span <= 0.0:
            return 0.0
        return (len(self._arrival_stamps) - 1) / span
