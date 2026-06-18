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

from ros_tui.ros.echo import EchoBuffer


def test_push_then_drain_delivers_in_order():
    buffer = EchoBuffer(maxlen=10)
    for value in range(5):
        buffer.push(value)
    messages, received, dropped, _ = buffer.drain()
    assert messages == [0, 1, 2, 3, 4]
    assert received == 5
    assert dropped == 0


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


def test_rate_estimate_positive_after_bursts():
    buffer = EchoBuffer(maxlen=5, hz_window=8)
    for value in range(8):
        buffer.push(value)
    _, _, _, rate_hz = buffer.drain()
    assert rate_hz > 0.0


def test_rate_zero_with_single_message():
    buffer = EchoBuffer()
    buffer.push('only')
    _, _, _, rate_hz = buffer.drain()
    assert rate_hz == 0.0
