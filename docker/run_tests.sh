#!/usr/bin/env bash
# Run the ros_tui test suite inside the Docker playground.
#
# The container entrypoint (docker/entrypoint.sh) has already sourced ROS, built the
# workspace with --symlink-install, and sourced the overlay, so here we just run pytest
# from the package source. Any extra arguments are forwarded to pytest. Examples:
#
#   docker compose run --rm ros_tui src/ros_tui/docker/run_tests.sh           # full suite
#   docker compose run --rm ros_tui src/ros_tui/docker/run_tests.sh -m ui     # UI tests only
#   docker compose run --rm ros_tui src/ros_tui/docker/run_tests.sh -k node_info -q
set -e
cd /ros_tui_ws/src/ros_tui
exec python3 -m pytest "$@"
