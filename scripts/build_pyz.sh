#!/usr/bin/env bash
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

# Build dist/ros_tui.pyz: the whole app, bundled textual included, as one executable file.
# It runs with the system python3 and takes rclpy (and the message packages) from the sourced
# ROS environment, so one file serves every distro:
#
#   scripts/build_pyz.sh
#   source /opt/ros/jazzy/setup.bash && dist/ros_tui.pyz
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

cp -r "$repo/ros_tui" "$staging/ros_tui"
find "$staging" -name __pycache__ -type d -prune -exec rm -rf {} +
cat > "$staging/__main__.py" <<'PY'
import sys

try:
    import rclpy  # noqa: F401
except ImportError:
    sys.exit('ros_tui needs a ROS 2 environment: source /opt/ros/<distro>/setup.bash first.')

from ros_tui.main import main

sys.exit(main())
PY
mkdir -p "$repo/dist"
python3 -m zipapp "$staging" --compress --python '/usr/bin/env python3' --output "$repo/dist/ros_tui.pyz"
echo "built $repo/dist/ros_tui.pyz ($(du -h "$repo/dist/ros_tui.pyz" | cut -f1))"
