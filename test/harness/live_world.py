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

"""The nav model with the real entries over a FakeBridge, without textual (the model tests).

``live_nav`` builds it as the app does, over ``FakeBridge.demo()`` unless given a bridge. Time only
moves in ``advance``, which ticks the model every 0.1 s as the app's timer does, so echoes drain,
answers arrive and toasts expire at known moments. Without a ``post`` the entries apply bridge
answers in place, and without a ``work`` they load message types in place.
"""

from harness.fake_bridge import FakeBridge
from ros_tui.constants import UI_TICK_PERIOD_S
from ros_tui.ui.entries.kinds import entry_factory
from ros_tui.ui.feedback import Feedback
from ros_tui.ui.nav import NavState


def live_nav(*keys: str, bridge: FakeBridge | None = None, work=None) -> tuple[NavState, FakeBridge]:
    """A NavState over `bridge` (default: the live demo world) after pressing `keys`."""
    bridge = bridge or FakeBridge.demo()
    nav = NavState(entry_factory(bridge, work=work), Feedback(bridge.now, bridge.time_of_day))
    nav.set_catalog(bridge.latest_graph)
    press(nav, *keys)
    return nav, bridge


def press(nav: NavState, *keys: str) -> None:
    for key in keys:
        nav.handle_key(key)


def advance(nav: NavState, bridge: FakeBridge, seconds: float) -> int:
    """Move the clock in UI_TICK_PERIOD_S steps, ticking the model after each; how many ticks asked
    to redraw."""
    redraws = 0
    for _ in range(round(seconds / UI_TICK_PERIOD_S)):
        bridge.clock.advance(UI_TICK_PERIOD_S)
        redraws += bool(nav.tick())
    return redraws


def activity(nav: NavState) -> list[str]:
    """The activity lines' texts, newest first."""
    return [line.text for line in nav.feedback.activity]


def toast(nav: NavState) -> str | None:
    return nav.feedback.toast.text if nav.feedback.toast else None
