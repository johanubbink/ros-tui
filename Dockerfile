# syntax=docker/dockerfile:1
# A lean ROS 2 environment for trying out ros_tui against a set of example servers.
# Headless (no X11) — see docker-compose.yml / README.md "Try it in Docker".
ARG ROS_DISTRO=jazzy
FROM ros:${ROS_DISTRO}-ros-base

# ---- Dependencies -----------------------------------------------------------
# colcon + build tooling, the message packages the demo node and app need at
# runtime, and the test deps so `colcon test` / pytest also work in here.
#
# `apt-get upgrade` first: the ros:${ROS_DISTRO}-ros-base layer is rebuilt less
# often than the ROS apt repo updates, so freshly installing packages like
# example_interfaces on top of it can pull a newer build than the fastcdr/rmw
# already baked in. The ABI then mismatches and FastDDS serialization aborts
# with an undefined-symbol error (e.g. the /fibonacci action or any action send).
# Upgrading realigns the whole ROS stack so a build is reproducible whenever it runs.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ros-dev-tools \
        ros-${ROS_DISTRO}-example-interfaces \
        ros-${ROS_DISTRO}-rosidl-runtime-py \
        ros-${ROS_DISTRO}-domain-coordinator \
        ros-${ROS_DISTRO}-test-msgs \
        ros-${ROS_DISTRO}-turtlesim \
        ros-${ROS_DISTRO}-tf-transformations \
        python3-numpy \
        python3-yaml \
        python3-pip \
        python3-pytest \
        python3-pytest-asyncio \
        sudo vim less \
    && rm -rf /var/lib/apt/lists/*

# textual (and a recent rich) are not reliably packaged for apt at the versions the
# app needs; CI installs them via pip too (see .github/workflows/python-package.yml).
# --ignore-installed: install textual's dep tree into /usr/local (which shadows the
# apt copies) rather than trying to uninstall Debian-managed packages like Pygments.
RUN pip install --no-cache-dir --break-system-packages --ignore-installed textual rich

# ---- Non-root user, mapped to the host UID/GID ------------------------------
# Files written to the bind-mounted source then belong to the host user.
# Robust against pre-existing group/user (Ubuntu 24.04 base ships an 'ubuntu'
# user/group at 1000), so any host UID/GID combination works.
ARG USERNAME=dev
ARG USER_ID=1000
ARG GROUP_ID=1000
RUN set -eux; \
    if ! getent group "${GROUP_ID}" >/dev/null; then \
        groupadd --gid "${GROUP_ID}" "${USERNAME}"; \
    fi; \
    if getent passwd "${USER_ID}" >/dev/null; then \
        old="$(getent passwd "${USER_ID}" | cut -d: -f1)"; \
        usermod -l "${USERNAME}" -d "/home/${USERNAME}" -m -g "${GROUP_ID}" "${old}"; \
    else \
        useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --create-home --shell /bin/bash "${USERNAME}"; \
    fi; \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME}; \
    chmod 0440 /etc/sudoers.d/${USERNAME}

# Workspace dir (the source is bind-mounted into src/ at runtime); build/install/
# log land here, inside the container, keeping the host repo clean.
RUN mkdir -p /ros_tui_ws/src && chown -R "${USER_ID}:${GROUP_ID}" /ros_tui_ws

# Source ROS + the workspace overlay for every shell flavor a user can land in:
# login shells (e.g. `docker compose exec ... bash -lc '...'`) read /etc/profile.d,
# while interactive shells (`docker compose exec ros_tui bash`) read ~/.bashrc. The
# stock ~/.bashrc returns early for non-interactive shells, so the profile.d copy is
# what makes the one-shot `bash -lc` form work.
RUN printf '%s\n' \
        "source /opt/ros/${ROS_DISTRO}/setup.bash" \
        "[ -f /ros_tui_ws/install/setup.bash ] && source /ros_tui_ws/install/setup.bash" \
    > /etc/profile.d/ros_tui_env.sh
RUN printf '%s\n' \
        "source /etc/profile.d/ros_tui_env.sh" \
        "cd /ros_tui_ws" \
    >> /home/${USERNAME}/.bashrc

USER ${USERNAME}
WORKDIR /ros_tui_ws
CMD ["bash"]
