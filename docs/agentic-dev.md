# Agentic development

The "Hybrid Keys" redesign was built in steps, each by two agents: an
implementation agent and a verification agent. They work from screenshots,
because a UI change is only done when it *looks* like the design. This page
covers the tools they share and the protocol between them; both still apply to
any later UI change. A human can use the same tools. How each step was verified
is recorded in [`verification/`](../verification/).

- The design: [`docs/design/hybrid-keys.html`](design/hybrid-keys.html), a JS
  simulation of the UI. Open it in a browser and use the keyboard.
- The rules: [`docs/design-principles.md`](design-principles.md). Read it before
  a step; the verification agent keeps it up to date.

## The harness

### One command

```bash
scripts/agent_check.sh                       # flake8 + the whole suite, shots on
scripts/agent_check.sh -m shots              # flake8 + only the screenshot scenarios
scripts/agent_check.sh test/ui/test_harness.py -q
ROS_TUI_SHOTS=0 scripts/agent_check.sh       # no artifacts
```

It runs in the Docker playground image (`docker compose run`), because the host
may have no textual or ROS. It runs flake8 the way CI does: real errors fail the
run, and style issues are listed but don't fail it. Then it runs pytest with
`ROS_TUI_SHOTS=1`, passing on any arguments you give it. At the end it prints
the artifact folder and the `manifest.md` of every test that wrote shots. Its
exit status is pytest's.

If the image is older than `docker/Dockerfile`, rebuild it once with
`docker compose build`. It needs `librsvg2-bin` for PNGs and
`fonts-jetbrains-mono`. Without `rsvg-convert` the shots are still written as
SVG, TXT and JSON, with a warning.

### Writing a scenario

Scenario tests live in `test/ui/test_<what>.py` and are marked
`ui` and `shots`:

```python
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]


async def test_echo_chatter():
    async with ui_session() as s:                    # FakeBridge.demo(), 124x34
        await s.keys('slash', *'chat', 'enter')      # textual key names
        await s.keys('space')                        # start the echo
        await s.advance(3.0)                         # simulated seconds
        assert "'chatter 3'" in s.text()
        await s.shot('echo-live', expect="LATEST MESSAGE shows data 'chatter 3', 3 received · 1.0 Hz")
```

- `ui_session(size=(124, 34), bridge=None, test_id=None)` runs `RosTuiApp`
  headless under Pilot. The default bridge is `FakeBridge.demo()`; the
  end-to-end tests pass the real `RosBridge`.
- `s.keys(*keys)` presses keys one at a time and lets the app go idle after each
  one, including its workers.
- `s.type_text('abc')` types characters.
- `s.advance(seconds)` moves the fake bridge's clock forward in 0.1 s steps.
  After each step the UI drains what was pushed, so a 1 Hz topic shows every
  message. Nothing in the fake world happens until you advance it.
  The app's `tick()` runs once per step, so echoes drain and toasts expire on
  the simulated clock too.
- `s.wait_until(predicate)` polls in real time, for the UI's own timers (e.g. the
  filter debounce).
- `s.text()` is the screen as plain text and `s.state()` is the state summary.
  Assert on them.
- `s.shot(name, expect=...)` takes a numbered shot. `expect` is a sentence for
  the verifier: what a person should see in the picture. Make it concrete
  ("RESPONSE shows ✓ OK and sum: 42"), not vague ("it works").
- The artifact folder is named after the running test's node id
  (`PYTEST_CURRENT_TEST`); pass `ui_session(test_id=...)` outside pytest.

### The fake world

[`test/harness/fake_bridge.py`](../test/harness/fake_bridge.py) has
`FakeBridge`: the bridge contract without rclpy. It records every call.

- `FakeBridge()` is **canned**, over the same world: nothing happens on its
  own. Node requests answer at once, and a test sends action events by hand
  (`bridge.on_event(...)`). Some entry unit tests use it.
- `FakeBridge.demo()` is **live** over `DEMO_GRAPH`, the same world as
  `ros_tui/demo/demo_servers.py` and the design. It has six topics, `/add_two_ints`
  and `/set_pose`, `/fibonacci`, and the nodes `/ros_tui_demo_servers` and
  `/talker`.
  - Services answer 0.05 s after the call (AddTwoInts returns the real sum,
    TeleportAbsolute its empty response). A service name in
    `bridge.failing_services` (name → reason) fails its calls with a
    `TimeoutError` of that reason.
  - Node requests (`get_node_info`, `list_node_parameters`, `set_node_parameter`)
    answer 0.05 s later too, so a node entry shows "loading…" until you advance.
    A set changes what later lists return. A parameter name in
    `bridge.rejected_params` (name → reason) fails its set with that reason.
  - Actions are accepted, send a feedback every 0.3 s, then succeed. A cancel
    gives `CANCEL_ACCEPTED`, then a `CANCELED` result. An action name in
    `bridge.failing_actions` fails its goals: `'rejected'` (rejected at once),
    `'aborted'` (an `ABORTED` result halfway through its feedback) or any other
    text (an `ERROR` event with that text, as when no server answers).
    `rotate_demo()` adds a second action, `/turtle1/rotate_absolute`, for the
    single-running-goal rule.
  - Echo subscriptions get messages at each topic's rate: /chatter 1 Hz,
    /counter 50 Hz, /diagnostic_status 1 Hz, /localisation_pose 2 Hz. Topics
    nobody publishes stay silent, but what the UI publishes on a topic (once,
    or repeated at its rate) loops back into an echo on it, and a repeating
    topic counts as published. `bridge.periodic_sent` counts each repeat's
    sends.
  - Everything is driven by `bridge.clock` (a `ManualClock`), so the same keys
    and advances always give the same screen.
    `time_of_day()` is 09:41:00 plus the clock, so activity lines read `09:41:03`.

The UI reads time from the bridge's clock (see the code principles in
design-principles.md), so every number on screen is repeatable: a demo service
call always takes `50.0 ms`, and activity lines start at `09:41:00`.

The JSON state includes `NavState.summary()` (layer, mode, breadcrumb, open
tabs, register).

### Artifacts

Everything lands in `test/artifacts/`, which git ignores. It is also uploaded
as the `ui-screenshots` build artifact on pull requests.

```
test/artifacts/
  ui__test_topic__test_echo_chatter/              # one folder per test (its node id)
    manifest.md                                   # per shot: keys since the last shot, all keys, expect
    01-chatter-open.png  01-chatter-open.svg  01-chatter-open.txt  01-chatter-open.json
    02-echo-live.png …
  design/                                         # from scripts/design_shots.py
    manifest.md
    home.png  echo-frozen.png …
```

- `.png` is the shot to look at, rendered from the SVG by `rsvg-convert` in
  JetBrains Mono.
- `.svg` is textual's own screenshot.
- `.txt` is the screen as plain text. Use it to check exact strings.
- `.json` holds `name`, `expect`, `keys_since_last_shot`, `keys` and `state`.
  `state` has the screen, the screen stack, the focused widget (always none)
  and the `NavState` summary.

A test's folder is wiped when the test starts, so it always shows the latest
run.

### Design reference shots

```bash
scripts/design_shots.py                      # every shot in docs/design/reference_shots.json
scripts/design_shots.py echo-frozen home     # some of them
scripts/design_shots.py --keys '/,a,d,d,enter,space,wait1000' --name add-called
```

This runs on the host, not in Docker, because it needs Google Chrome or
Chromium. It opens the design with `#keys=…` in headless Chrome at 1440×900 and
writes `test/artifacts/design/<name>.png`. The page plays the keys into its
terminal, 120 ms apart. Key names are `enter esc space tab up down left right
backspace`, plus modifiers like `shift+tab` and `ctrl+s`, single characters
(`/`, `:`, `G`), and `waitN` to pause for N ms of page time.

Each step adds the references it needs to
[`docs/design/reference_shots.json`](design/reference_shots.json), as a name,
the keys, and what the shot shows.

## The two agents

### Implementation agent: make it work

Input: the step's row from the plan, the design and the line ranges in it to
mirror, `docs/design-principles.md` and this page.

1. Implement the step.
2. Write or extend `test/ui/test_<what>.py` with named `shot(…, expect=…)`s for every
   state the step's criteria mention. Assert on `s.text()` and `s.state()` too,
   so the test fails even when nobody looks at the pictures.
3. Add the step's design references to `reference_shots.json`.
4. Run `scripts/agent_check.sh` until it is green. Look at your own PNGs.
5. Report the files you touched, the commands you ran and their results, the
   artifact paths, and anything that deviates from the plan.

Don't commit. Don't gold-plate: cleanup is the verification agent's job.

### Verification agent: check it, then clean it up

The verification agent is a fresh agent that shares no context with the
implementation agent. It has three jobs.

1. **Behaviour.**
   - Re-run `scripts/agent_check.sh` and `scripts/design_shots.py <the step's
     references>`.
   - Open every PNG and compare it with its `expect` text, its `.txt` dump and
     the design reference.
   - Check each of the step's criteria.
   - Small visual differences from the prototype are fine (terminal cells
     aren't CSS pixels). Missing information, wrong layer or mode, and wrong
     key behaviour are not.
2. **Code quality.**
   - Review `git diff`. Check that it matches the surrounding style, and look
     for duplicated logic, logic in widgets that belongs in the pure model
     (`nav.py`, `fields.py`), dead code, unclear names and weak tests.
   - Then **simplify and clean up the code yourself**.
   - Re-run `scripts/agent_check.sh` to prove nothing changed: the same tests
     green and the same shots.
3. **Principles.** Check the step against `docs/design-principles.md`. Add any
   new rule or pattern the step introduced.

It writes its verdict to `verification/stepNN.md`:

```markdown
# Step NN — <name>: PASS | FAIL

Ran: scripts/agent_check.sh (N passed), scripts/design_shots.py a b c

## Criteria
| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | esc returns to the exact previous layer | PASS | 03-search.png → 04-closed.png, state.layer |
| 2 | … | FAIL | 05-x.png shows …, the design (design/x.png) shows … |

## Cleanups made
- moved the breadcrumb logic from widgets/footer.py into NavState.footer()
- …

## Open defects
- (for FAIL) what is wrong, where, and what the design wants

## Principles doc
- added: …
```

### Loop limits

If behaviour FAILs, the open defects go to a new implementation agent. That
happens **at most twice** per step. If the step still fails after the second
retry, stop and ask the user. Don't start a third round. When the step PASSes,
it is committed on `feature/update-ui`, one commit per step.
