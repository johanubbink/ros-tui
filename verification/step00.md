# Step 00 — Agentic dev harness: PASS

Ran:
- `scripts/agent_check.sh -q`: 246 passed (before and after cleanups); the flake8 error pass is clean
- `scripts/agent_check.sh -m shots -q`: 3 passed, 243 deselected; it wrote 2 artifact folders
- `ROS_TUI_SHOTS=0 scripts/agent_check.sh test/ui -q`: 3 passed, 0 files written, "(no shots written by this run)"
- `python3 scripts/design_shots.py`: 9 reference PNGs and a manifest in about 4 s

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| H1 | Shared `FakeBridge` and `DEMO_GRAPH`, live services, actions and echo, `ManualClock` | PASS | `test/harness/fake_bridge.py`. AddTwoInts returns the real sum (`02-response`: `sum: 42`). /chatter pushes at 1 Hz on the manual clock: `+3s` gives exactly chatter 1–3 and no chatter 4 (the test asserts this), and nothing arrives after unsubscribe. `test_manual_clock_orders_timers` covers ordering and cancel. `DEMO_GRAPH` lists the 6 topics, /add_two_ints, /set_pose (TeleportAbsolute), /fibonacci, /ros_tui_demo_servers and /talker. The demo node got /goal_pose and /set_pose. |
| H1 | `test_ui_pilot.py` still uses the canned bridge correctly | PASS | It imports the entries and `FakeBridge` from the harness. `FakeBridge()` keeps the old canned defaults (`SNAPSHOT`, `NODE_INFO`, futures pending until the test resolves them), and all of its tests pass. |
| H2 | `ui_session`, `keys`, `shot` writing svg, png, txt, json and manifest, gated by `ROS_TUI_SHOTS` | PASS | 5 shots, each with all 4 files and a manifest section. With `ROS_TUI_SHOTS=0` nothing is written. The `shots` marker is in `pytest.ini`. |
| H2 | PNGs legible, txt and png agree, expect matches what's visible | PASS | I read all 5 PNGs: JetBrains Mono, leading spaces kept. `01-start`: six topics, filter focused. `02-mode-popup`: "Topic: /chatter", std_msgs/msg/String, publishers: 1. `03-echo-live`: data: chatter 1/2/3. `01-request`: a: 19, b: 23. `02-response`: "response in … ms", sum: 42. Each txt has the same content as its PNG. |
| H3 | Dockerfile deps, `agent_check.sh`, `.gitignore`, CI artifact upload | PASS | The image has rsvg-convert and the font. The script prints the manifests written by the run and exits with pytest's status. The flake8 error pass is the same command as CI. The style pass adds `--select=E,W,F,C90` to drop the docstring and import-order plugins from ros-dev-tools; it is non-fatal, as in CI. |
| H4 | Design copy with the `#keys=` hook, `design_shots.py`, reference shots | PASS | I read all 9 PNGs and each shows what its `shows` claims. home: the ☰ list grouped by kind. chatter-open: tab 1, "not echoing". echo-live: ◉ in the tab and top bar, "● live". echo-frozen: "❄ FROZEN +3 new since", footer "latest message", "esc go live". search-open: SEARCH, "add" matching /add_two_ints. command-line: COMMAND with suggestions. which-key: the popup with Layers/Move/Go/Help. service-response: "✓ OK 4.0 ms", sum: 42. goal-pose-quat-helper: HELPER, yaw only, 90 → {z: 0.707107, w: 0.707107}. No key sequence needed fixing. |
| H5 | `docs/agentic-dev.md` | PASS | Covers running the harness, the artifact layout, both roles, the verdict format and the loop limits. |
| H6 | `docs/design-principles.md` | PASS (after edits) | All the sections the plan lists are there. I made the send rule precise (see below). |
| P0 | Two Pilot tests ported to `ui_session` on the current UI | PASS | `test/ui/test_step00_harness.py`: echo /chatter and call /add_two_ints. |
| P0 | `-m shots` produces readable PNG, txt and json; the design references render | PASS | See H2 and H4. |
| P0 | Same artifacts after the cleanups | PASS | The file lists are identical and the txt dumps and manifests are byte-identical. The two exceptions are the real-clock values: echo "0.7 Hz" became "0.8 Hz", and "response in 112.3 ms" became "108.2 ms". |

## Cleanups made

- `ros_tui/ros/echo.py`: added a public `EchoBuffer.pending()` (taken under the lock). This replaces the harness peeking at `_messages`.
- `test/harness/fake_bridge.py`: `pending_echo()` now uses `buffer.pending()`.
- `test/test_echo.py`: asserts `pending()` before and after a drain.
- `test/conftest.py`: removed the `test_id` fixture, so the file is back to its HEAD content. It duplicated the `PYTEST_CURRENT_TEST` fallback `ui_session` already has.
- `test/ui/test_step00_harness.py`: scenarios call a plain `ui_session()`.
- `test/harness/screens.py`: dropped the `_png_warned` global (pytest already groups repeated warnings). Dropped a redundant `' (call)'` strip in `artifact_dir_name`, since `current_test_id` already does it. Added a comment on why `_notifications` is read. Updated the docstring.
- `docs/agentic-dev.md`: the example uses `ui_session()`, the `test_id` fixture note is replaced, and the real-clock caveat points to the new rule.
- `docs/design-principles.md`: the "Why" #3 and keymap rule 3 now state exactly which keys send, following the prototype's `keyList()`. Space and ^s are the primary verb, and ^s also sends from Insert. `.` resends, listed under "Do (only these send)". `r` repeats a publish, listed under "Do". `s` only stops. Added a **(target)** code principle: time on screen comes from an injectable clock.

## Caveats decided

- **Real-clock values in shots** (the echo Hz from `EchoBuffer`'s `time.monotonic`, "response in … ms" in `services_tab`): deferred. The old tab modules are deleted in step 10, so this is documented in agentic-dev.md and added as a target code principle for the new UI. Step 6 (echo Hz) and step 5 (response timing) should read the bridge's clock. That needs a small `now()` on the bridge, driven by `ManualClock` in `FakeBridge`.
- **Private API**:
  - `_messages`: replaced by `EchoBuffer.pending()`.
  - `app._notifications`: kept, with a comment. textual 8.2.8 has no public accessor, and the Toast widgets appear a frame late. The new UI's own toasts should come through `harness_state()`.
  - `screen._compositor` and `app._background_screens`: kept. This is the same code as `App.export_screenshot` (checked against 8.2.8), so the SVG and the text come from one render.
- **agent_check lint**: the error pass matches CI exactly. The extra `--select` only applies to the non-fatal style pass. Kept.

## Open defects / deferred

- None blocking.
- The prototype contradicts itself: its header says "anything sent to the robot only goes out on space or ^s", but its `.` and `r` keys also send. The doc now describes the keyList behaviour. **User decision**: keep `.` and `r` as sending keys (the doc's current wording), or restrict them, e.g. make `r` only arm a repeat and have space start it.
- The old UI's echo footer reads 0.7–0.8 Hz for a simulated 1 Hz topic, because the arrival stamps use real time. This is cosmetic and covered by the deferred clock item.
- `design_shots.py` runs on the host only (it needs Chrome). That is by design and documented.

## Principles doc

- Made precise: which keys send (Why #3, keymap rule 3).
- Added: "Time on screen comes from an injectable clock (target)".
