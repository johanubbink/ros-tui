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

"""The agentic dev harness: a fake ROS world and a screenshot-taking UI session.

- ``fake_bridge``: ``FakeBridge`` (the bridge contract without rclpy), its ``ManualClock`` and the
  ``DEMO_GRAPH`` world that mirrors the demo servers.
- ``live_world``: ``live_nav`` and ``advance``, the nav model with the real entries over a
  ``FakeBridge``, for the model tests.
- ``nav_world``: a small fixed world with stand-in entries, for the pure nav-model tests.
- ``screens``: ``ui_session``, which drives the app headless and writes SVG / PNG / text / JSON
  shots into ``test/artifacts/`` when ``ROS_TUI_SHOTS=1``.

See docs/agentic-dev.md.
"""
