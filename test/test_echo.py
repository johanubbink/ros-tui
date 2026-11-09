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

"""Pure unit tests for the echo hand-off buffer."""

import pytest
from harness.fake_bridge import ManualClock
from ros_tui.ros.echo import EchoBuffer


def test_push_then_drain_delivers_in_order():
    buffer = EchoBuffer(maxlen=10)
    for value in range(5):
        buffer.push(value)
    assert buffer.pending() == 5
    messages, received, dropped, _ = buffer.drain()
    assert messages == [0, 1, 2, 3, 4]
    assert received == 5
    assert dropped == 0
    assert buffer.pending() == 0


def test_overflow_drops_oldest_and_counts():
    buffer = EchoBuffer(maxlen=5)
    for value in range(12):
        buffer.push(value)
    messages, received, dropped, _ = buffer.drain()
    assert messages == [7, 8, 9, 10, 11]
    assert received == 12
    assert dropped == 7


def test_drain_twice_accumulates_counts():
    buffer = EchoBuffer(maxlen=5)
    buffer.push('a')
    buffer.drain()
    buffer.push('b')
    messages, received, dropped, _ = buffer.drain()
    assert messages == ['b']
    assert received == 2
    assert dropped == 0


def pushed_at(stamps, hz_window=8, drained_at=None):
    """A buffer that received one message at each of ``stamps`` (seconds on a manual clock), and its
    rate when drained at ``drained_at`` (default: the last stamp)."""
    clock = ManualClock()
    buffer = EchoBuffer(hz_window=hz_window, clock=lambda: clock.now)
    for stamp in stamps:
        clock.advance(stamp - clock.now)
        buffer.push(stamp)
    if drained_at is not None:
        clock.advance(drained_at - clock.now)
    return buffer.drain()[3]


@pytest.mark.parametrize('stamps, hz_window, drained_at, rate_hz', [
    ([index * 0.01 for index in range(20)], 8, None, 100.0),       # 100 Hz
    ([index * 0.5 for index in range(5)], 8, None, 2.0),           # 2 Hz
    ([0.0, 0.1, 0.2, 1.2, 2.2, 3.2], 4, None, 1.0),                # Only the last hz_window arrivals count.
    ([0.0, 1.0, 2.0], 8, 3.9, 1.0),                                # Still fresh 1.9 s after the last arrival.
    ([0.0, 1.0, 2.0], 8, 4.1, 0.0),                                # Stale: nothing for over 2 s.
    ([0.0], 8, None, 0.0),                                         # One message gives no rate.
    ([1.0, 1.0, 1.0], 8, None, 0.0),                               # Arrivals at one instant give no rate.
])
def test_rate_over_the_last_arrivals(stamps, hz_window, drained_at, rate_hz):
    assert pushed_at(stamps, hz_window, drained_at) == pytest.approx(rate_hz)
