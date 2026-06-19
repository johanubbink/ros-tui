# ros_tui

A terminal UI for exploring and exercising a live ROS 2 system: browse **actions, services
and topics** in three tabs, fill in messages in a prefilled YAML editor, and send goals /
call services / publish / echo — without composing `ros2 ... "{...}"` one-liners.

```shell
ros2 run ros_tui ros_tui
```

Each tab: filterable entity list on the left · type + YAML editor + controls on the
right · output log at the bottom. The graph refreshes automatically (1 s poll, only
re-renders on change).

## Try it in Docker

Don't have a ROS 2 system handy? The bundled Docker playground spins up a small set of
example servers and lets you drive the TUI against them — no local ROS install required,
just Docker Engine + the Compose plugin (Linux).

```shell
./create_dot_env             # one-time: writes .env with your UID/GID (and ROS_DISTRO)
docker compose up --build    # builds the workspace, then launches the demo servers
```

Leave that running and, in a **second terminal**, open a shell in the same container and
start the TUI (it needs an interactive terminal, which a `docker compose exec` shell
provides):

```shell
docker compose exec ros_tui bash
# inside the container:
ros2 run ros_tui ros_tui
```

All three tabs populate from the demo node ([`launch/demo.launch.py`](launch/demo.launch.py)
→ [`ros_tui/demo/demo_servers.py`](ros_tui/demo/demo_servers.py)):

| Tab      | Entity              | Try                                                        |
|----------|---------------------|-----------------------------------------------------------|
| Actions  | `/fibonacci`        | Send `order: 8`; watch feedback stream, then `Cancel`.    |
| Services | `/add_two_ints`     | Call with `a: 19` / `b: 23` → `sum: 42`.                  |
| Topics   | `/chatter` (~1 Hz)  | `Echo` a calm `std_msgs/String` stream.                   |
| Topics   | `/counter` (~50 Hz) | `Echo` to watch the Hz / drop counters move.              |
| Topics   | `/inbox`            | `Publish` `data: hello` — it's logged by the demo node.   |

### With turtlesim (GUI)

For a richer, well-known target you can also launch **turtlesim** and watch the turtle move
in its window as you drive it from the TUI. This forwards a GUI window from the container, so
it needs an **X11 display** (Linux):

```shell
xhost +local:                                  # once per login: let the container reach your X server
docker compose -f docker-compose.yml -f docker-compose.gui.yml up --build
# second terminal, as before:
docker compose exec ros_tui bash
ros2 run ros_tui ros_tui
# when done, revoke access again:
xhost -local:
```

This adds the demo servers **and** turtlesim, so the TUI also lists:

| Tab      | Entity                       | Try                                                          |
|----------|------------------------------|--------------------------------------------------------------|
| Actions  | `/turtle1/rotate_absolute`   | Send `theta: 1.57`; watch the turtle rotate in the window.   |
| Services | `/spawn`                     | `x: 5.0` / `y: 5.0` / `name: t2` → a second turtle appears.  |
| Services | `/clear`                     | Wipes the trail.                                             |
| Topics   | `/turtle1/cmd_vel`           | `Start rate` a `Twist` with `linear: {x: 1.0}` → it drives.  |
| Topics   | `/turtle1/pose`              | `Echo` to watch x/y/theta update live.                       |

The plain `docker compose up` stays fully headless and needs none of this.

Notes:

- **Live edits.** The repo is bind-mounted and built with `colcon build --symlink-install`,
  so editing Python under `ros_tui/` is picked up on the next process start — no rebuild.
  Re-run `docker compose up --build` only after changing `package.xml`, `setup.py`, or the
  Dockerfile.
- **Run the tests in here too:** `docker compose exec ros_tui bash -lc 'colcon test --packages-select ros_tui && colcon test-result --verbose'`
  (the image ships the test deps).
- **Why `create_dot_env`?** It maps the container user to your host UID/GID so build
  artifacts stay yours. Compose falls back to `1000:1000` if you skip it.
- **Tear down:** `docker compose down`. The image is lean (`ros:jazzy-ros-base`, headless —
  no X11); switch distro or to a desktop image via the `ROS_DISTRO` / base-image build arg.

## Tabs

- **Actions** — select an action, edit the Goal (seeded with defaults), `Send goal`.
  The status line tracks SENDING → EXECUTING → SUCCEEDED/ABORTED/CANCELED, feedback streams
  into the log (coalesced at high rate), the result renders at the end. `Cancel` cancels.
- **Services** — edit the Request, `Call`, response + round-trip time in the log.
  No response within 30 s → timeout error.
- **Topics** — `Publish` once, or `Start rate` to publish periodically (0.1–100 Hz;
  periodic publishers keep running while you inspect other topics; the status line lists
  them; reselect the topic to stop, and everything stops on quit). `Echo` subscribes with
  QoS adapted to the live publishers (best-effort if any publisher is best-effort) and
  renders messages with array truncation, message/Hz/drop counters in the status line.
  QoS is captured when the echo starts — if a publisher with different QoS appears later,
  restart the echo.

## Editor

The editor speaks the same YAML dialect as `ros2 action send_goal` / `ros2 topic pub`,
prefilled with the message defaults. Extras:

- `stamp: now` and `header: auto` are stamped with the current time at send time
  (re-applied every tick for periodic publishing).
- `.nan` / `.inf` / `-.inf` for floats; unicode strings work.
- Everything is validated **before** sending — types, integer/float ranges, fixed-array
  sizes, bounded-sequence lengths — with the exact field path in the error
  (`pose.pose.position.x: could not convert string to float: 'oops'`). This is stricter
  than the stock ROS CLI, which silently truncates e.g. `UInt8(data=300)`.
- Per-entity edits are remembered for the session; `ctrl+r` reseeds the defaults.
- Message classes are imported lazily on first selection, so startup stays fast on
  systems with thousands of interfaces.

## Keybindings

`ctrl+1/2/3` tabs · `ctrl+f` filter · `ctrl+s` send/call/publish · `ctrl+k` cancel/stop ·
`ctrl+r` reset editor · `ctrl+l` clear log · `f1` help · `ctrl+q` quit. Mouse works.

Note: `ctrl+1/2/3` require a terminal with extended keyboard reporting (e.g. kitty,
recent VS Code); on plain xterm-likes click the tab titles instead.

## Tests

```shell
colcon test --packages-select ros_tui
# or, directly:
python3 -m pytest test -q
```

Pure unit tests (YAML round-trips over 28 interface types, edge cases like `byte`
corruption, NaN, range checks), bridge integration tests against in-process fixture
servers on an isolated `ROS_DOMAIN_ID`, headless UI tests (textual Pilot + a FakeBridge),
and a full-stack e2e smoke (real bridge + real servers driven through the real app).
A manual smoke checklist against the Docker demo playground lives in
`test/test_e2e_smoke.py`'s module docstring.

## Architecture notes

- One dedicated `ros-bridge` thread owns a private rclpy context/node/executor and every
  rclpy entity; the UI requests work via a guard-condition command queue and gets results
  back as futures/messages (`ros_tui/ros/bridge.py`). The `ros/` layer never imports
  textual; the `ui/` layer never touches rclpy directly.
- Servers are never awaited blockingly: readiness and response deadlines run on a 4 Hz
  housekeeping timer (5 s ready / 30 s response timeouts).
- Client/publisher objects are cached per (name, type) with LRU eviction (size 8) that
  skips in-use entities, keeping DDS resources bounded in long sessions.
- High-rate data never touches the UI thread directly: subscriptions append into a locked
  bounded buffer; the UI drains at 10 Hz and renders at most 3 messages per tick with
  drop counters.

If a noisy RMW prints C-level warnings that smear the TUI, run with
`ros2 run ros_tui ros_tui 2>>/tmp/ros_tui.stderr`.
