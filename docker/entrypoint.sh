#!/usr/bin/env bash
# Source ROS, build the workspace, source the overlay, then run the given command.
# Used as the container entrypoint (see compose.yaml). Building here means a
# fresh `docker compose up` always reflects the current source; --symlink-install
# makes it a fast no-op on re-up and picks up Python edits without a rebuild.
set -e

source "/opt/ros/${ROS_DISTRO}/setup.bash"

cd /ros_tui_ws
echo "[entrypoint] colcon build --symlink-install ..."
colcon build --symlink-install
source /ros_tui_ws/install/setup.bash
echo "[entrypoint] workspace ready."

if [ "$#" -eq 0 ]; then
    exec bash
fi
exec "$@"
