# Docker playground

The playground runs ros_tui against a set of example servers in a container,
so you can run it without ROS on your machine. You need Docker Engine with the
Compose plugin (Linux).

```bash
docker/create_dot_env            # once: writes .env with your UID/GID
docker compose up --build        # builds the workspace, then starts the demo servers
```

Leave that running. In a second terminal, open a shell in the same container
and start the TUI (it needs an interactive terminal, which `exec` gives you):

```bash
docker compose exec ros_tui bash
ros2 run ros_tui ros_tui         # inside the container
```

`docker compose down` removes the container when you're done.

## What to try

The demo node ([`docker/demo_servers.py`](../docker/demo_servers.py)) gives every
kind something to do. Open each with `/` and its name, then `enter`:

| Kind    | Entry                    | Try                                                         |
| ------- | ------------------------ | ----------------------------------------------------------- |
| action  | `/fibonacci`             | `enter enter`, type `8`, `esc`, space sends the goal; watch the feedback, then `s` cancels it. |
| service | `/add_two_ints`          | `enter enter 19 tab 23 esc`, then space → `sum: 42`.        |
| service | `/plan_to_pose`          | A `nav_msgs/GetPlan`: unfold `goal` and set a position, then space; the response is a straight path from start to goal. |
| topic   | `/chatter` (~1 Hz)       | Opens in Echo: space echoes a calm `std_msgs/String` stream; `enter` freezes it. |
| topic   | `/counter` (~50 Hz)      | Echo it to watch the count, the Hz and the drops move.      |
| topic   | `/localisation_pose`     | A nested message: echo it, or `e` to publish one with the Quaternion helper (`f`). |
| topic   | `/inbox`                 | Opens in Publish: type `hello` into `data`, space publishes it; the demo node logs it. |
| topic   | `/goal_pose`             | Publish a `PoseStamped` with the Header and Quaternion helpers; the demo node logs it. |
| topic   | `/diagnostic_status`     | `e` for Publish, then `f` on `level` picks OK / WARN / ERROR / STALE. |
| node    | `/ros_tui_demo_servers`  | Browse its interfaces (`enter` opens one); change `publish_rate` and set it with space (only the demo parameter changes; nothing reads it). |

## How it's put together

| File                                                     | What it does |
| -------------------------------------------------------- | ------------ |
| [`compose.yaml`](../compose.yaml)                        | The `ros_tui` service and its image, `ros-tui-dev:<distro>-<uid>-<gid>`. Mounts the repo at `/ros_tui_ws/src/ros_tui` and runs the demo servers. |
| [`docker/Dockerfile`](../docker/Dockerfile)              | `ros:jazzy-ros-base` plus the dependencies in `package.xml` (installed with rosdep, as CI does), flake8, and `rsvg-convert` with the JetBrains Mono font for the screenshot PNGs. textual comes bundled with ros_tui. Adds a non-root user matching your UID/GID, with sudo. |
| [`docker/entrypoint.sh`](../docker/entrypoint.sh)        | Sources ROS, runs `colcon build --symlink-install`, sources the overlay, then runs the command. |
| [`docker/create_dot_env`](../docker/create_dot_env)      | Writes `.env` with `USER_ID`, `GROUP_ID` and `ROS_DISTRO`. |
| [`docker/run_tests.sh`](../docker/run_tests.sh)          | Runs pytest in the container (see [testing.md](testing.md)). |

Notes:

- **Edits show up without a rebuild.** The source is bind-mounted and built
  with `--symlink-install`, so a change under `ros_tui/` is picked up the next
  time you start a process. Rebuild (`docker compose up --build`) only after
  changing `package.xml` or the Dockerfile.
- **One image per distro.** The image is `ros-tui-dev:<distro>-<uid>-<gid>`
  (for example `ros-tui-dev:jazzy-1000-1000`), whatever folder you run Compose
  from, so every clone and git worktree with the same `.env` uses the same
  image; each still mounts its own source. Containers stay per folder, so two
  worktrees can run at the same time.
- **Why `create_dot_env`?** The container user gets your UID/GID, so files it
  writes into the mounted repo (caches, the GIF) belong to you. Without `.env`,
  Compose uses `1000:1000`. The UID/GID is baked into the image and part of
  its tag, so give a new clone or worktree your `.env` (copy it, or run
  `create_dot_env` there) to share your image.
- **Another distro.** Set `ROS_DISTRO` in `.env` (or the environment) to build
  on a different `ros:<distro>-ros-base` image. CI tests Jazzy, Lyrical and
  Rolling.
