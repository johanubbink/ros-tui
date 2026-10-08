# Screenshots and the UI harness

A UI change is only done when it looks right, so the UI tests drive the app by
keys and take named screenshots that an agent (or a person) can look at. This
page is how to run them, write them and read their output. The rules the UI
follows are in [design-principles.md](design-principles.md).

## One command

```bash
scripts/agent_check.sh                       # flake8 + the whole suite, shots on
scripts/agent_check.sh -m shots              # flake8 + only the screenshot scenarios
scripts/agent_check.sh test/ui/test_topic.py -q
ROS_TUI_SHOTS=0 scripts/agent_check.sh       # no artifacts
```

It runs in the Docker playground image (`docker compose run`), because the host
may have no textual or ROS. It runs flake8 the way CI does (real errors fail the
run, style issues are listed), then pytest with `ROS_TUI_SHOTS=1` and any
arguments you give it. At the end it prints the artifact folder and the
`manifest.md` of every test that wrote shots. Its exit status is pytest's.

If the image is older than `docker/Dockerfile`, rebuild it with
`docker compose build`. PNGs need `librsvg2-bin` and `fonts-jetbrains-mono`;
without `rsvg-convert` the shots are still written as SVG, TXT and JSON, with a
warning.

## Writing a scenario

Scenario tests live in `test/ui/test_<what>.py` and are marked `ui` and `shots`:

```python
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]


async def test_echo_chatter():
    async with ui_session() as s:                    # FakeBridge.demo(), 124x34
        await s.keys('slash', *'chat', 'enter')      # textual key names
        await s.keys('space')                        # start the echo
        await s.advance(3.0)                         # simulated seconds
        assert s.line_with('[x] data', "'chatter 3'")
        await s.shot('echo-live', expect="LATEST MESSAGE shows data 'chatter 3', 3 received · 1.0 Hz")
```

`ui_session(size=(124, 34), bridge=None, test_id=None)` runs `RosTuiApp`
headless and yields a `UiSession`
([`test/harness/screens.py`](../test/harness/screens.py)). The default bridge is
the live `FakeBridge.demo()`; the end-to-end tests pass the real `RosBridge`.

- `s.keys(*keys)` presses keys one at a time and settles the app after each;
  `s.type_text('abc')` types characters; `s.click(x, y)` and
  `s.click_on(text)` click a cell or what the screen shows.
- `s.advance(seconds)` moves the fake bridge's `ManualClock` in 0.1 s steps and
  ticks the app after each (its real-time tick timer is paused), so echoes,
  answers, toasts and spinners follow simulated time.
- `s.wait_until(predicate)` polls in real time, for a real bridge.
- `s.text()`, `s.lines()`, `s.line_with(*parts)` and `s.footer()` read the
  screen; `s.state()` is `NavState.summary()` plus the screen stack, and
  `s.where(*keys)` picks values from it. Assert on these, not on the app's
  internals.
- `s.shot(name, expect=...)` takes a numbered shot. `expect` says concretely
  what a person should see ("RESPONSE shows ✓ OK and sum: 42").

### How the session settles the app

`UiSession` does not use Pilot's `press`/`click`/`pause`: they wait for the
process to go idle by CPU time, which ROS threads in the same process keep
busy. Instead `idle()` drains the screen's message queues, waits for workers,
and runs the screen's layout and repaint itself until nothing is pending, so no
real time passes and the result is deterministic. This uses private textual
APIs: `Pilot._wait_for_screen`, `Screen._on_timer_update`, `Screen._forward_event`,
the `_layout_required` / `_repaint_required` / `_scroll_required` /
`_refresh_styles_required` / `_dirty_widgets` flags, `screen._compositor` and
`app._background_screens` (for rendering), and
`textual.keys._character_to_key` / `_get_unicode_name_from_key` and
`textual.pilot._get_mouse_message_arguments` (to build events). **A textual
upgrade may need fixes here.**

## The fake world

[`test/harness/fake_bridge.py`](../test/harness/fake_bridge.py) has
`FakeBridge`, the bridge contract without rclpy. It records every call.

- `FakeBridge()` is canned: nothing happens on its own; node requests answer at
  once and a test sends action events by hand.
- `FakeBridge.demo()` is live over `DEMO_GRAPH`, the world of
  `docker/demo_servers.py`: six topics, `/add_two_ints`, `/set_pose`,
  `/fibonacci`, and the nodes `/ros_tui_demo_servers` and `/talker`.
  - Services and node requests answer 0.05 s after the call. Names in
    `bridge.failing_services`, `bridge.rejected_params` or
    `bridge.failing_actions` fail with the given reason.
  - Actions are accepted, send feedback every 0.3 s, then succeed; a cancel
    gives a `CANCELED` result. `rotate_demo()` adds a second action.
  - Echoes get messages at each topic's rate (/chatter 1 Hz, /counter 50 Hz, …),
    and what the UI publishes loops back into an echo on that topic.
  - Everything runs on `bridge.clock`, and `time_of_day()` is 09:41:00 plus the
    clock, so every number on screen is repeatable (a demo call takes `50.0 ms`).

## Artifacts

With `ROS_TUI_SHOTS=1`, shots land in `test/artifacts/` (git-ignored; uploaded
as the `ui-screenshots` build artifact on pull requests), one folder per test,
wiped when the test starts:

```
test/artifacts/ui__test_topic__test_echo_chatter/
  manifest.md                     # per shot: keys since the last shot, all keys, expect
  01-chatter-open.png  .svg  .txt  .json
  02-echo-live.png …
```

- `.png`: the shot to look at, the SVG rendered by `rsvg-convert` in JetBrains Mono.
- `.svg`: textual's own screenshot.
- `.txt`: the screen as plain text, for exact strings.
- `.json`: `name`, `expect`, `keys_since_last_shot`, `keys` and `state`.

Outside pytest, pass `ui_session(test_id=...)` to name the folder.

## Checking a UI change

Look at every new or changed PNG next to its `expect` text and `.txt` dump.
Missing information, the wrong layer or mode, and wrong key behaviour are bugs;
small differences in spacing usually aren't. Assert the important strings in
the test as well, so it fails even when nobody looks at the pictures.
