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

"""Entry point: start the ROS bridge thread, run the TUI, tear down in order."""

import argparse
import sys

from ros_tui.ros.bridge import RosBridge
from ros_tui.ui.app import RosTuiApp
from ros_tui.ui.next_app import NextApp


def main(args=None):
    parser = argparse.ArgumentParser(prog='ros_tui', description='ROS 2 interface workbench')
    parser.add_argument('--next', action='store_true', help='run the new "Hybrid Keys" UI (in development)')
    options, _ = parser.parse_known_args(sys.argv[1:] if args is None else args)  # Leaves --ros-args alone.
    app_class = NextApp if options.next else RosTuiApp
    bridge = RosBridge()
    bridge.start()
    try:
        app_class(bridge).run()
    finally:
        bridge.shutdown()


if __name__ == '__main__':
    main()
