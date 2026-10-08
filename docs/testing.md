# Testing

The tests are pytest, in [`test/`](../test/). They come in five kinds, the last
three selected with markers (see [`pytest.ini`](../pytest.ini)):

| Kind        | Marker      | Files                                                           | What                                                                     |
| ----------- | ----------- | --------------------------------------------------------------- | ------------------------------------------------------------------------ |
| model       | (none)      | `test_nav.py`, `test_keymap.py`, `test_fields.py`, `test_entries_*.py`, `test_helpers.py`, `test_register.py`, `test_widgets.py`, `test_harness.py` | The UI's model without running the app: layers and overlays (`NavState` over a fixed catalog with stand-in entries, `harness/nav_world.py`), the keymap (and that `docs/usage.md` lists it), the field rows, each entry kind and the field helpers over a `FakeBridge` (`harness/live_world.py`: `live_nav`, `press`, `advance`), the widgets' pure layout helpers, the harness's clock. |
| unit        | (none)      | `test_message_yaml.py`, `test_message_display.py`, `test_echo.py`, `test_graph.py` | Pure logic, no rclpy node: message round trips over many interface types, range and size checks, `byte`/NaN edge cases, display truncation, the echo buffer, the graph. |
| bridge      | `ros_graph` | `test_bridge.py`                                                | The real `RosBridge` against in-process fixture servers.                 |
| UI          | `ui`, `shots` | `ui/test_*.py`                                                | Scenarios: the textual app headless, driven by keys against the live `FakeBridge.demo()` world (no rclpy), with named screenshots. |
| end to end  | `e2e`       | `test_e2e_smoke.py`                                             | The real app, driven by keys, over the real bridge and the fixture servers: echo, publish, call, send a goal, set a parameter. |

The ROS tests run on an isolated `ROS_DOMAIN_ID` (from `domain_coordinator`),
so they don't see or disturb other ROS nodes on the machine. The fixture
servers are in [`test/conftest.py`](../test/conftest.py) and mirror the demo
node.

## Running them

With ROS 2 sourced and the package built:

```bash
colcon test --packages-select ros_tui && colcon test-result --verbose
# or straight from the repo:
python3 -m pytest
python3 -m pytest -m ui           # one kind
python3 -m pytest -m "not e2e"    # skip the slowest
```

Without ROS on your machine, run them in the [Docker playground](docker.md),
which has every test dependency:

```bash
docker compose run --rm ros_tui src/ros_tui/docker/run_tests.sh        # everything
docker compose run --rm ros_tui src/ros_tui/docker/run_tests.sh -m ui  # one kind
```

Extra arguments go straight to pytest. The whole suite takes under a
minute.

CI runs flake8, a colcon build and the whole suite on every push and pull
request to `main`, once per distro: [`jazzy.yml`](../.github/workflows/jazzy.yml),
[`lyrical.yml`](../.github/workflows/lyrical.yml) and
[`rolling.yml`](../.github/workflows/rolling.yml) each call
[`test.yml`](../.github/workflows/test.yml) in a `ros:<distro>-ros-base`
container, with the dependencies from `package.xml` through rosdep. One
workflow per distro gives each its own badge in the README.
[`release.yml`](../.github/workflows/release.yml) builds `ros_tui.pyz`, and on a
`v*` tag attaches it to the GitHub release.

## Screenshot harness

[`test/harness/`](../test/harness/) has the shared `FakeBridge` (canned, or a
live simulated world on a manual clock: the demo servers' graph, answering
services, actions and node requests, and echo feeds), the model tests' worlds
(`nav_world.py`, `live_world.py`), and `ui_session`, which drives the app by keys and takes
named screenshots. With `ROS_TUI_SHOTS=1` the scenario tests in `test/ui/` (and
the end-to-end tests) write PNG, SVG, text and JSON shots to `test/artifacts/`.
One command runs flake8 and the suite in Docker with shots on:

```bash
scripts/agent_check.sh               # everything
scripts/agent_check.sh -m shots      # only the scenarios
scripts/agent_check.sh test/ui/test_topic.py -q
```

How it works and the artifact layout are in [agentic-dev.md](agentic-dev.md).

### Where a test goes

Test a behaviour once, at the cheapest level that shows it: rules, messages,
toasts, undo and what the bridge was asked go in the model tests; a UI scenario
drives the keys a person would and checks what the screen shows (and takes the
shots), without re-asserting the model's facts. UI tests read state through
`s.state()` / `s.where()` and the screen through `s.line_with()` / `s.footer()`.

## Manual checks

Some things are easier to check by hand: a smooth UI under a 50 Hz echo,
publishers stopping on quit. The checklist is in the module docstring of
[`test/test_e2e_smoke.py`](../test/test_e2e_smoke.py); run it against the
playground.

## Demo GIF

[`scripts/make_gif.py`](../scripts/make_gif.py) remakes
`assets/ros-tui-demo.gif`. It isn't part of the test suite. It starts the demo
servers on their own `ROS_DOMAIN_ID`, runs the real app headless under the
harness's `UiSession` (a subclass that pauses after each key), types its way
through an echo of /chatter, a call of /add_two_ints, a
/fibonacci goal and a node's parameters, and saves a screenshot of every
change. `rsvg-convert` turns the screenshots into PNGs (prepared by the
harness's `rsvg_ready`, as the shots are), and ffmpeg makes the
GIF with each frame held for as long as it was on screen.

The playground image has `rsvg-convert` but not ffmpeg, so install it first:

```bash
docker compose run --rm ros_tui bash -lc '
  sudo apt-get update && sudo apt-get install -y ffmpeg &&
  src/ros_tui/scripts/make_gif.py'
```

Change the steps in `demo()` in the script to change what the GIF shows.
