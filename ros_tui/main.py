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

"""Entry point: pick a backend, start its bridge thread, run the TUI, tear down in order."""

import argparse

from ros_tui.ui.app import RosTuiApp


def parse_args(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='ros_tui',
        description='Terminal UI for exploring and exercising a ROS 2 system.',
    )
    parser.add_argument(
        '--foxglove',
        metavar='URL',
        default=None,
        help=(
            'Connect to a Foxglove WebSocket bridge (e.g. ws://localhost:8765) instead of the '
            'local ROS 2 graph. Needs no ROS install; requires the [foxglove] extra.'
        ),
    )
    # Tolerate stray args (e.g. a --ros-args tail from `ros2 run`) rather than erroring.
    namespace, _ = parser.parse_known_args(args)
    return namespace


def build_bridge(opts: argparse.Namespace):
    """Construct the backend selected by ``opts``. Imports are lazy so the Foxglove path never
    touches rclpy and the native path never touches websockets/rosbags."""
    if opts.foxglove:
        from ros_tui.foxglove.bridge import FoxgloveBridge

        return FoxgloveBridge(opts.foxglove)
    from ros_tui.ros.bridge import RosBridge

    return RosBridge()


def main(args=None):
    opts = parse_args(args)
    bridge = build_bridge(opts)
    bridge.start()
    try:
        RosTuiApp(bridge).run()
    finally:
        bridge.shutdown()


if __name__ == '__main__':
    main()
