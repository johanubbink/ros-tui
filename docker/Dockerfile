# syntax=docker/dockerfile:1
# A lean ROS 2 environment for trying out ros_tui against a set of example servers.
# Headless (no X11) — built by compose.yaml at the repo root; see docs/docker.md.
ARG ROS_DISTRO=jazzy
FROM ros:${ROS_DISTRO}-ros-base
ARG ROS_DISTRO

# ---- Dependencies -----------------------------------------------------------
# package.xml is the one list of ROS and Python dependencies: rosdep installs them, as CI does.
# Only package.xml is copied in, so this layer is rebuilt only when it changes. The base image
# already has colcon and rosdep. textual is not installed here: the entrypoint unpacks ros_tui's
# bundled copy (scripts/vendor.py, no pip) into the mounted source.
# Outside rosdep, as in CI: flake8 for scripts/agent_check.sh, and librsvg2-bin +
# fonts-jetbrains-mono, with which the harness turns screenshot SVGs into PNGs in the design's
# monospace font. sudo lets the playground user install extra tools (docs/testing.md: ffmpeg).
# The apt cache mounts (one per distro) keep downloaded packages between builds, so a rebuild
# after a package.xml change only fetches what is new.
# `apt-get upgrade` first: a local ros:<distro>-ros-base can be older than the ROS apt repo, and a
# package installed fresh on top of it (example_interfaces, say) may be built against a newer
# fastcdr/rmw than the one in the base. FastDDS then aborts on an undefined symbol (e.g. on an
# action send). Upgrading aligns the whole ROS stack; when the base is current it changes nothing.
COPY package.xml /tmp/ros_tui_deps/ros_tui/package.xml
RUN --mount=type=cache,id=ros-tui-apt-${ROS_DISTRO},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=ros-tui-apt-lists-${ROS_DISTRO},target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    && rosdep update --rosdistro "${ROS_DISTRO}" \
    && DEBIAN_FRONTEND=noninteractive rosdep install --from-paths /tmp/ros_tui_deps --ignore-src -y \
        --rosdistro "${ROS_DISTRO}" \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3-flake8 librsvg2-bin fonts-jetbrains-mono sudo \
    && rm -rf /tmp/ros_tui_deps /root/.ros

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
