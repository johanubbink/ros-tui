# Docker playground

The playground runs ros_tui against a set of example servers in a container,
so you can try it without ROS on your machine. You need Docker Engine with the
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

The demo node ([`launch/demo.launch.py`](../launch/demo.launch.py) →
[`ros_tui/demo/demo_servers.py`](../ros_tui/demo/demo_servers.py)) gives every
tab something to do:

| Tab      | Entity                   | Try                                                         |
| -------- | ------------------------ | ----------------------------------------------------------- |
| Actions  | `/fibonacci`             | Send `order: 8`; watch the feedback stream, then **Cancel**. |
| Services | `/add_two_ints`          | Call with `a: 19`, `b: 23` → `sum: 42`.                     |
| Topics   | `/chatter` (~1 Hz)       | Subscribe and **Echo** a calm `std_msgs/String` stream.     |
| Topics   | `/counter` (~50 Hz)      | **Echo** it to watch the Hz and drop counters move.         |
| Topics   | `/localisation_pose`     | A nested message: pick fields to echo, or publish one with the Quaternion helper. |
| Topics   | `/inbox`                 | **Publish** `data: hello`; the demo node logs it.           |
| Topics   | `/diagnostic_status`     | **Publish**: put the cursor on `level` and press `ctrl+w` to pick OK/WARN/ERROR/STALE. |
| Nodes    | `/ros_tui_demo_servers`  | Browse its interfaces (jump to one); view or **Set** a parameter. |

## With turtlesim

For something you can see move, add turtlesim. Its window is shown on your
desktop, so this needs an X11 display (Linux):

```bash
xhost +local:                    # once per login: let the container reach your X server
docker compose -f compose.yaml -f docker/compose.gui.yaml up --build
# second terminal, as before:
docker compose exec ros_tui bash
ros2 run ros_tui ros_tui
# when you're done:
xhost -local:
```

This runs the demo servers **and** turtlesim, so you also get:

| Tab      | Entity                     | Try                                                           |
| -------- | -------------------------- | ------------------------------------------------------------- |
| Actions  | `/turtle1/rotate_absolute` | Send `theta: 1.57`; the turtle turns.                         |
| Services | `/spawn`                   | `x: 5.0`, `y: 5.0`, `name: t2` → a second turtle appears.     |
| Services | `/clear`                   | Wipes the trail.                                              |
| Topics   | `/turtle1/cmd_vel`         | **Start rate** with `linear: {x: 1.0}` → it drives.           |
| Topics   | `/turtle1/pose`            | **Echo** to watch x, y and theta change.                      |

The plain `docker compose up` stays headless and needs none of this.

## How it's put together

| File                                                     | What it does |
| -------------------------------------------------------- | ------------ |
| [`compose.yaml`](../compose.yaml)                        | The `ros_tui` service. Mounts the repo at `/ros_tui_ws/src/ros_tui` and runs the demo launch file. |
| [`docker/Dockerfile`](../docker/Dockerfile)              | `ros:jazzy-ros-base` plus colcon, the message packages the demo and tests need, turtlesim, pytest, and textual/rich from pip. Adds a non-root user matching your UID/GID. |
| [`docker/compose.gui.yaml`](../docker/compose.gui.yaml)  | The turtlesim overlay: X11 socket, `DISPLAY`, software rendering. |
| [`docker/entrypoint.sh`](../docker/entrypoint.sh)        | Sources ROS, runs `colcon build --symlink-install`, sources the overlay, then runs the command. |
| [`docker/create_dot_env`](../docker/create_dot_env)      | Writes `.env` with `USER_ID`, `GROUP_ID` and `ROS_DISTRO`. |
| [`docker/run_tests.sh`](../docker/run_tests.sh)          | Runs pytest in the container (see [testing.md](testing.md)). |

Notes:

- **Edits show up without a rebuild.** The source is bind-mounted and built
  with `--symlink-install`, so a change under `ros_tui/` is picked up the next
  time you start a process. Rebuild (`docker compose up --build`) only after
  changing `package.xml`, `setup.py` or the Dockerfile.
- **Why `create_dot_env`?** The container user gets your UID/GID, so files it
  writes into the mounted repo (caches, the GIF) belong to you. Without `.env`,
  Compose uses `1000:1000`.
- **Another distro.** Set `ROS_DISTRO` in `.env` (or the environment) to build
  on a different `ros:<distro>-ros-base` image. Only Jazzy is tested.
