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

"""The harness's simulated clock (harness.fake_bridge.ManualClock), which the fake world runs on."""

from harness.fake_bridge import ManualClock


def test_manual_clock_orders_timers():
    clock = ManualClock()
    fired = []
    clock.call_every(0.5, lambda: fired.append(('every', clock.now)))
    timer = clock.call_later(0.75, lambda: fired.append(('later', clock.now)))
    clock.call_later(0.25, timer.cancel)
    clock.advance(1.0)
    assert fired == [('every', 0.5), ('every', 1.0)]
    assert clock.now == 1.0
