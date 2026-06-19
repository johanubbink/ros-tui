# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`ros_tui` is a Textual terminal UI for exploring and exercising a live ROS 2 graph
(actions, services, topics) — an `ament_python` package targeting ROS 2 Jazzy. The
end-user feature set lives in `README.md`; this file is about building, testing, and the
internal architecture.

## Commands

All commands assume ROS 2 Jazzy is sourced (`. /opt/ros/jazzy/setup.sh`) and `textual` is
importable (it is installed via pip, not apt — see CI / Dockerfile). Run from the colcon
workspace root (the dir containing `src/`), not from this package dir.

```sh
colcon build --symlink-install --packages-select ros_tui   # --symlink-install: Python edits need no rebuild
ros2 run ros_tui ros_tui                                   # run the TUI against the current graph

# Tests — pytest can run directly from this package dir (pytest.ini sets testpaths=test):
python3 -m pytest test -q                  # full suite
python3 -m pytest -m ui -q                 # one layer (markers: ros_graph | ui | e2e)
python3 -m pytest test/test_message_yaml.py::test_name -q   # single test
colcon test --packages-select ros_tui && colcon test-result --verbose   # the colcon way

# Lint — CI passes these flags inline (there is no flake8 config file):
python3 -m flake8 ros_tui test --select=E9,F63,F7,F82 --show-source   # hard errors (fail build)
python3 -m flake8 ros_tui test --exit-zero --max-complexity=10 --max-line-length=127   # advisory
```

The `ros_graph` and `e2e` markers need rclpy + the message packages from `package.xml`'s
`<test_depend>` (example_interfaces, std_srvs, geometry_msgs, sensor_msgs, test_msgs,
turtlesim, domain_coordinator). The `ui` markers need only textual. If you can't source ROS
locally, use the **Docker playground** (`README.md` "Try it in Docker"): `./create_dot_env`
then `docker compose up --build` brings up a fully-provisioned environment; the entrypoint
runs `colcon build` on every `up`.

## Architecture

### The hard layering rule
Two layers with a one-way dependency, and it is load-bearing:
- **`ros_tui/ros/`** owns all rclpy/DDS interaction. **It must never import textual.**
- **`ros_tui/ui/`** owns all Textual widgets. **It must never touch rclpy directly** — it
  goes through `RosBridge`.
- `ros_tui/main.py` is the only place that wires the two together (start bridge thread → run
  app → shut down in order).

This is what makes the UI testable headless with a `FakeBridge` (the `ui` test layer) and the
bridge testable without any UI (the `ros_graph` layer).

### The bridge thread model (`ros/bridge.py`) — read this before touching bridge code
`RosBridge` runs **one dedicated thread** that owns a *private* rclpy context, node, executor,
and **every** rclpy entity (clients, publishers, subscriptions, action clients, goal handles).
The reason: creating/destroying rclpy entities from a foreign thread races the executor's wait
set. So nothing outside that thread is allowed to construct or destroy an entity.

The mechanism: callers from the UI thread enqueue a closure via `submit()` / the internal
`_guarded()` helper; `submit()` triggers a `GuardCondition` that wakes the executor, which runs
`_drain_commands()` **on the ROS thread**. Results flow back to the caller via
`concurrent.futures.Future` or via callbacks — **and those callbacks fire on the ROS thread**,
so they must be cheap and thread-safe. The UI's callbacks do nothing but `post_message(...)`
(handing the data to Textual's own event loop). When adding a bridge operation, follow this
pattern: public method builds a closure, submits it, returns a Future; never poke rclpy from
the calling thread.

Supporting pieces, all driven from that one thread:
- **Graph polling** (`ros/graph.py`): polled at `GRAPH_POLL_PERIOD_S` (1 s) into an immutable,
  version-stamped `GraphSnapshot`; the registered graph listener is invoked **only when the
  snapshot changes**. The app registers a listener that posts a `GraphUpdated` message.
- **Housekeeping timer** (`HOUSEKEEPING_PERIOD_S`, 0.25 s): servers are *never* awaited
  blockingly. Readiness (`READY_TIMEOUT_S` 5 s) and response deadlines (`RESPONSE_TIMEOUT_S`
  30 s) are checked here.
- **Client/publisher cache**: keyed by `(name, type)` with LRU eviction (`CLIENT_CACHE_SIZE`)
  that skips in-use entities, to keep DDS resources bounded in long sessions.
- **Echo** (`ros/echo.py`): subscriptions append into a locked bounded `EchoBuffer`; the UI
  drains it (~10 Hz, ≤3 msgs/tick) with drop counters, so high-rate data never blocks the UI
  thread. Subscription QoS is computed by `adapted_qos()` (best-effort if any publisher is).

### Message YAML (`ros/message_yaml.py`)
Implements the YAML dialect of `ros2 action send_goal` / `ros2 topic pub`, plus stricter
validation. Key entry points: `default_yaml()` (seed the editor), `build_message()` (YAML →
typed message, returning `TimeSetter`s for `stamp: now` / `header: auto`), `to_truncated_yaml()`
(render incoming messages with array/string truncation). Validation happens **before** sending:
field types, int/float ranges, fixed-array sizes, bounded-sequence lengths — raising `FieldError`
with the exact dotted field path. Types are imported lazily (`import_type`) and cached, so startup
stays fast on systems with thousands of interfaces.

### UI tabs (`ui/`)
`ui/app.py` hosts three tabs over one shared bridge. `ui/interface_tab.py` is the
`InterfaceTab` base class (entity list + filter + YAML editor + output log + the prototype-load
flow); `ActionsTab`, `ServicesTab`, `TopicsTab` subclass it and override the hooks
`compose_controls` / `compose_status` / `primary_action` / `secondary_action` /
`on_selection_changed`. Cross-thread/cross-widget signalling uses Textual `Message` types in
`ui/messages.py` (e.g. `GraphUpdated`, `PrototypeReady`). All tunable numbers live in
`ros_tui/constants.py` — change them there, not inline.

### Styling
The visual system is documented in `docs/STYLE_GUIDE.md` and lives in three modules:
`ui/theme.py` (the `ros-dark` `Theme` — the whole palette), `ui/styles.py` (the glyph +
semantic-colour vocabulary for log/status text — call its builders, never raw Rich style
strings), and `RosTuiApp.CSS` in `ui/app.py` (layout/spacing/borders). The hard rule: **all
colour comes from theme variables** (`$primary`, `$text-success`, …), never hardcoded hex,
so themes stay switchable. `ui/resize_grip.py` is the draggable seam between the two panes.

## Tests
`pytest.ini` defines three markers that map to the three test layers — keep new tests in the
right one so the layering stays honest:
- **`ros_graph`** — real `RosBridge` against in-process fixture servers on an isolated
  `ROS_DOMAIN_ID` (`test/conftest.py`: `ros_domain` / `fixture_servers` / `bridge` fixtures).
- **`ui`** — Textual app headless via `Pilot` with a `FakeBridge`, no rclpy.
- **`e2e`** — full stack (real bridge + Pilot + fixture servers); `test/test_e2e_smoke.py` also
  carries a manual checklist (run against the Docker demo playground) in its module docstring.

Pure unit tests (`test_message_yaml.py`, `test_truncated_yaml.py`) have no marker and need
neither rclpy nor textual.

## Demo / playground
`ros_tui/demo/demo_servers.py` (console script `demo_servers`) is an installable node that
mirrors the test `FixtureServers`, exposing one entity per tab under public-looking names
(`/fibonacci`, `/add_two_ints`, `/chatter`, `/counter`, `/inbox`).
`launch/demo.launch.py` launches it, with a `turtlesim:=true` arg to additionally bring up
turtlesim (GUI; needs an X display — wired through `docker-compose.gui.yml`).
