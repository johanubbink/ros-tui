# Testing

The tests are pytest, in [`test/`](../test/). They come in five kinds, the last
three selected with markers (see [`pytest.ini`](../pytest.ini)):

| Kind        | Marker      | Files                                                           | What                                                                     |
| ----------- | ----------- | --------------------------------------------------------------- | ------------------------------------------------------------------------ |
| model       | (none)      | `test_nav.py`, `test_keymap.py`, `test_fields.py`, `test_entries_*.py`, `test_helpers.py`, `test_register.py`, `test_widgets.py`, `test_harness.py` | The UI's model without running the app: layers and overlays (`NavState` over a fixed catalog with stand-in entries, `harness/nav_world.py`), the keymap (and that `docs/usage.md` lists it), the field rows, each entry kind and the field helpers over a `FakeBridge` (`harness/live_world.py`: `live_nav`, `press`, `advance`), the widgets' pure layout helpers, the harness's clock. |
| unit        | (none)      | `test_message_yaml.py`, `test_message_display.py`, `test_echo.py`, `test_graph.py`, `test_contract.py`, `test_vendor_script.py` | Pure logic, no rclpy node: message round trips over many interface types, range and size checks, `byte`/NaN edge cases, display truncation, the echo buffer, the graph, that `RosBridge` and `FakeBridge` both implement the bridge contract (and the UI calls nothing else), what `scripts/vendor.py` unpacks from a wheel. |
| bridge      | `ros_graph` | `test_bridge.py`, `test_bridge_offline.py`                      | The real `RosBridge` against in-process fixture servers.                 |
| UI          | `ui`, `shots` | `ui/test_*.py`                                                | Scenarios: the textual app headless, driven by keys against the live `FakeBridge.demo()` world (no rclpy), with named screenshots. |
| end to end  | `e2e`       | `test_e2e_smoke.py`                                             | The real app, driven by keys, over the real bridge and the fixture servers: echo, publish, call, send a goal, set a parameter. |

The ROS tests run on an isolated `ROS_DOMAIN_ID` (from `domain_coordinator`),
so they don't see or disturb other ROS nodes on the machine.
`scripts/agent_check.sh` also keeps discovery inside its container
(`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`): `domain_coordinator` picks a free
domain only within one container, and parallel runs share the compose network,
so without it two runs can pick the same domain and answer each other. The fixture
servers are in [`test/conftest.py`](../test/conftest.py) and mirror the demo
node; one instance serves the whole run, because a node re-created under the
same name is slow to be discovered again.

## Two tiers

| Tier    | Selected by          | What                                                                                   | Who runs it |
| ------- | -------------------- | -------------------------------------------------------------------------------------- | ----------- |
| fast    | `-m "not offline"`   | model, unit and UI tests, and `test_bridge.py`: the bridge's handling of rclpy entities on its ROS thread, plus one smoke test per way it talks over DDS (graph, service, publish, subscribe, action, parameters) | CI, on every distro; the implementer while it works |
| offline | the `offline` marker | `test_bridge_offline.py` (the rest of the bridge over DDS: timeouts, cancels, shutdown, node info) and `test_e2e_smoke.py` | `scripts/agent_check.sh` by default; the reviewer before it passes a change |

The fast tier is deterministic: nothing in it depends on how fast the machine
is, apart from the DDS smoke tests, which wait only for outcomes. A new
real-ROS test goes in the offline tier unless it is the one smoke test for a
new way the bridge talks to other nodes.

### Real-ROS tests wait for outcomes, never for time

A test over real DDS runs on a machine that may be loaded by parallel agents and
builds. So it:

- asserts only an outcome that eventually arrives (a response, a message, an
  event, a value on the node), polling with `wait_for` or `UiSession.wait_until`
  up to `EVENTUALLY_S` (15 s): a slow machine makes the test slower, never red;
- never asserts a rate, an elapsed time, or that nothing happens within some
  seconds;
- never sleeps to order things: wait for the state that should come first (on
  the node, or in the app's model) before acting on it or taking a shot.

Whatever is quantitative or about time is tested deterministically instead: on
a clock the test controls (`EchoBuffer(clock=…)`, the `FakeBridge`'s
`ManualClock`) or by what the bridge set up on its ROS thread (the timer
period it created, the timer or subscription it destroyed). A real-ROS test
may add one long-timeout check that something eventually stops (as
`test_periodic_publish_reaches_the_node_until_shutdown` does), since that can
only pass late, never fail early.

## Running them

With ROS 2 sourced and the package built:

```bash
colcon test --packages-select ros_tui && colcon test-result --verbose
# or straight from the repo:
python3 -m pytest                      # both tiers
python3 -m pytest -m "not offline"     # the fast tier, as CI runs it
python3 -m pytest -m ui                # one kind
```

Without ROS on your machine, use `scripts/agent_check.sh` (below), or run
pytest in the [Docker playground](docker.md), which has every test dependency:

```bash
docker compose run --rm ros_tui src/ros_tui/docker/run_tests.sh                    # both tiers
docker compose run --rm ros_tui src/ros_tui/docker/run_tests.sh -m "not offline"   # the fast tier
```

Extra arguments go straight to pytest. The fast tier takes about 15 s, both
tiers together about a minute.

CI runs flake8, a colcon build and the fast tier on every push and pull
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
scripts/agent_check.sh               # both tiers
scripts/agent_check.sh --fast        # the fast tier only, as CI runs it
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
