# Testing

The tests are pytest, in [`test/`](../test/). They come in four kinds,
selected with markers (see [`pytest.ini`](../pytest.ini)):

| Kind        | Marker      | Files                                                           | What                                                                     |
| ----------- | ----------- | --------------------------------------------------------------- | ------------------------------------------------------------------------ |
| unit        | (none)      | `test_message_yaml.py`, `test_truncated_yaml.py`, `test_echo.py`, `test_graph.py`, `test_field_wizards.py` | Pure logic, no rclpy node: YAML round trips over many interface types, range and size checks, `byte`/NaN edge cases, truncation, the echo buffer, the wizard helpers. |
| bridge      | `ros_graph` | `test_bridge.py`                                                | The real `RosBridge` against in-process fixture servers.                 |
| UI          | `ui`        | `test_ui_pilot.py`, `test_ctrl_t_focus.py`                      | The textual app headless under Pilot, against a `FakeBridge` (no rclpy). |
| end to end  | `e2e`       | `test_e2e_smoke.py`                                             | The real app, the real bridge and real fixture servers together.         |

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

Extra arguments go straight to pytest. The whole suite takes about 1.5
minutes.

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs flake8
and the whole suite in an `osrf/ros:jazzy-desktop` container on every push and
pull request to `main`.

## Manual checks

Some things are easier to check by hand: a smooth UI under a 50 Hz echo,
publishers stopping on quit, turtlesim moving. The checklist is in the module
docstring of [`test/test_e2e_smoke.py`](../test/test_e2e_smoke.py); run it
against the playground with turtlesim.

## Demo GIF

[`scripts/make_gif.py`](../scripts/make_gif.py) remakes
`assets/ros-tui-demo.gif`. It isn't part of the test suite. It starts the demo
servers on their own `ROS_DOMAIN_ID`, runs the real app headless under Pilot,
types its way through the four tabs, and saves a screenshot of every change.
`rsvg-convert` turns the screenshots into PNGs, and ffmpeg makes the GIF with
each frame held for as long as it was on screen.

It needs `rsvg-convert` and `ffmpeg`, which the playground image doesn't
include, so install them first:

```bash
docker compose run --rm ros_tui bash -lc '
  sudo apt-get update && sudo apt-get install -y librsvg2-bin ffmpeg fonts-firacode &&
  src/ros_tui/scripts/make_gif.py'
```

Change the steps in `demo()` in the script to change what the GIF shows.
