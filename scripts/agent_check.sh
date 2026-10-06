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

# One command for agents (and humans): flake8 as CI runs it, then pytest with screenshots on,
# inside the Docker playground image. Arguments go to pytest. See docs/agentic-dev.md.
#
#   scripts/agent_check.sh                          # lint + the whole suite
#   scripts/agent_check.sh -m shots                 # lint + only the screenshot scenarios
#   scripts/agent_check.sh test/ui/test_harness.py -q
#   ROS_TUI_SHOTS=0 scripts/agent_check.sh          # same, but write no artifacts
#
# Shots land in test/artifacts/<test id>/ on the host (the repo is bind-mounted); the paths of the
# folders and manifests written by this run are printed at the end.
set -uo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
mkdir -p test/artifacts
marker="$(mktemp)"
trap 'rm -f "$marker"' EXIT

# -T: no pseudo-TTY, so this works from agents and CI-like shells.
docker compose run --rm -T -e ROS_TUI_SHOTS="${ROS_TUI_SHOTS:-1}" ros_tui bash -c '
    set -e
    cd /ros_tui_ws/src/ros_tui
    echo "[agent_check] flake8 (errors)"
    python3 -m flake8 ros_tui test --count --select=E9,F63,F7,F82 --show-source --statistics
    # The CI style pass, minus the docstring/import-order plugins ros-dev-tools adds to this image.
    echo "[agent_check] flake8 (style, as CI: reported, not fatal)"
    python3 -m flake8 ros_tui test --count --exit-zero --max-complexity=10 --max-line-length=127 \
        --select=E,W,F,C90 --statistics
    echo "[agent_check] pytest $*"
    exec python3 -m pytest "$@"
' agent_check "$@"
status=$?

echo
echo "[agent_check] artifacts: $repo/test/artifacts"
manifests="$(find test/artifacts -name manifest.md -newer "$marker" 2>/dev/null | sort)"
if [ -n "$manifests" ]; then
    while IFS= read -r manifest; do
        echo "  $repo/$manifest"
    done <<< "$manifests"
else
    echo "  (no shots written by this run)"
fi
echo "[agent_check] exit status $status"
exit "$status"
