# Step 07 — Action entry (and simpler undo): PASS

Ran:
- `ROS_TUI_SHOTS=1 scripts/agent_check.sh test/ui/test_step07_action.py test/test_entries_action.py -q`: 17 passed, before the cleanups.
- After the cleanups:
  - The step's tests together with the topic tests: 68 passed.
  - `test/test_bridge.py`: 25 passed, including the new shutdown test.
  - The full `scripts/agent_check.sh -q` twice. The second run gave `644 passed`, exit 0 both times, and nothing flaked.
  - flake8 found no errors. The two E501 lines are fixed, and the C901 warnings in `bridge.py` were already there.
  - The step 4–7 shot `.txt` dumps are identical across the two runs.
- `python3 scripts/design_shots.py action-executing action-blocked action-canceled action-succeeded` on the host. I read every PNG in `test/artifacts/ui__test_step07_action__test_action_entry/` and compared it with those four.
- A real run in the container: `ros_tui.demo.demo_servers` plus `NextApp` over a real `RosBridge` under Pilot, from a throwaway script that I deleted afterwards.
  - Sent order 20 to /fibonacci. Feedback grew from 3 to 6 in 1 s, and the spinner showed `◓ running`.
  - `s` gave CANCELED with the last feedback `[0 … 13]` and the activity line `■ goal canceled after 1.8 s`. The demo server logged `/fibonacci: canceled`.
  - Sent order 5, which SUCCEEDED in 1.2 s.
  - An idle app over 1 s: 10 ticks, 0 redraws. A goal running while the ☰ list is shown: 10 ticks, 4 redraws.
  - Sent order 40, then `:q` mid-goal. The demo server logged `/fibonacci: canceled` right after the quit, and `bridge.shutdown()` returned at once.

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Shot: executing | PASS | `02-action-executing` vs `design/action-executing`: <ul><li>Send goal is dim (`off`) and `■ Cancel goal s` has the orange stop look.</li><li>RESULT shows the cyan EXECUTING pill and `0.9 s · live feedback`.</li><li>`sequence: [0, 1, 1, 2, 3]`, which grows in `03`.</li><li>The tab shows `/fibonacci ◒` and the top bar `▷ ◒ /fibonacci`.</li><li>`04-home-running`: Here says `◓ running open`.</li></ul> |
| 2 | Shot: succeeded | PASS | `08` vs `design/action-succeeded`: the green SUCCEEDED pill, `1.8 s`, the result sequence, `[ ] history (2)`, and `✓ goal succeeded · 1.8 s` in green. |
| 3 | Shot: canceled | PASS | `07` vs `design/action-canceled`: the yellow CANCELED pill, `2.4 s · last feedback` with the last sequence, and `■ goal canceled after 2.4 s` in yellow. No spinner is left, Send is blue again and Cancel is dim. |
| 4 | Shot: blocked second goal | PASS | `05` vs `design/action-blocked`: on the rotate tab, Send is dim and followed by `a goal is running on /fibonacci`, and Cancel is dim. The errline and a red ACTIVITY line both say `✗ a goal is already running on /fibonacci`. On the goal's own tab, the text adds ` — s cancels it`. |
| 5 | Single-running-goal rule | PASS | `executing()` is app-wide. Unit tests cover the same action and a second one: `s` on another tab cancels nothing, and a new goal can go out once the first ends or fails. |
| 6 | Spinner | PASS | The frame comes from the clock at `ACTION_SPINNER_HZ`, so the tab, the top bar and Here always show the same frame. It survives closing the tab (`10-closed-still-running`). Redraws: at most 4 a second on another tab (unit test and the real run), and none when idle. |
| 7 | Threading | PASS | <ul><li>FEEDBACK only `push`es into the goal's `EchoBuffer` on the ROS thread, and the tick drains it.</li><li>The other events are converted to plain data on the ROS thread and `post`ed.</li><li>Every event is bound to its own `Goal`, and `_update` ignores events once `goal.end` is set. So a stale event can't touch a newer goal.</li></ul> |
| 8 | Long result wraps | PASS (after fix) | `11-action-wrapped`: `55, 89, 144]` wraps onto an indented second line, and the row band covers both lines. `wrapped()` counted characters; it now counts cells, with a test on wide characters. |
| 9 | Undo simplified | PASS | `u` says exactly `nothing to undo here` in the log and the toast. The counts are gone from `nav.py`, the tests, the docs and the design's `undo()`. No dead code is left (grep). The keymap label is unchanged and matches the design. |
| 10 | Goal canceled on quit | PASS (implemented) | `RosBridge._cancel_goals()` runs in `_teardown`: <ul><li>It cancels every accepted goal, and one still waiting for acceptance once it is accepted.</li><li>It spins for at most `SHUTDOWN_CANCEL_TIMEOUT_S` (1 s), well inside the 3 s join.</li></ul> New test `test_bridge_shutdown_cancels_a_running_goal` checks that the fixture server ended the goal as canceled. That test fails with the call removed. The real run confirmed it. |

## Decisions applied

- Undo has exactly one message and no counts.
- Quitting cancels a running goal (see 10). This is documented in `architecture.md` "Shutdown" and in design-principles "Running".
- GOAL and RESULT keep their 3:2 widths, and the `[ ] earlier goals` hint stays.
- I didn't add a second demo action. `rotate_demo()` stays test-only.

## Cleanups made

- `ros_tui/ros/bridge.py`, `constants.py`: `_cancel_goals()` and `SHUTDOWN_CANCEL_TIMEOUT_S`, as decided.
- `test/conftest.py` and `test/test_bridge.py`: the fixture counts `canceled_goals`, and there is a new shutdown-cancels test.
- `ros_tui/ui/entries/action.py` fixes one bug: `s` while the goal was SENDING was lost on the real bridge, which only cancels accepted goals. The goal stayed "canceling…" and could not be canceled again. The cancel is now kept and sent on ACCEPTED, with the test `test_s_before_the_goal_is_accepted_cancels_it_once_it_is`.
- `action.py`: `tick` is simplified and the module doc is updated (quit, early `s`).
- `ros_tui/ui/widgets/panel.py`: `wrapped()` counts cells (`_chars_within` with `rich.cells.cell_len`).
- `ros_tui/ui/widgets/field_rows.py`: the new `shown_value(row)` replaces the same value, colour and enum code in `topic_entry.latest_panel` and `action_entry.result_panel`. RESULT's lines are now one comprehension.
- `widgets/activity_strip.py` and `test/ui/test_step06_topic.py`: fixed the E501 lines.
- Docs:
  - `design-principles.md`: quitting stops everything, including goals; an `s` before acceptance; stale events; wrap counts cells; the pill list is clearer.
  - `architecture.md`: the Shutdown section.

I reviewed and kept:
- `ActionEntry` is thin on `MessageEntry`. It adds only the goal, the RESULT rows and send/cancel.
- The action toolbar. Factoring the Send/Call/Publish toolbars wouldn't simplify anything: each is 3–10 lines, built from the `button`/`spread`/`keyed` helpers.
- The `off` button look, the `y` activity class, and the fake bridge's `failing_actions` / `rotate_demo`.

## Remaining gaps (not blocking)

- In `07-action-canceled`, the `nothing to undo here` toast from shot 06 still shows. The scenario doesn't advance the clock between the two shots.
- On the real bridge, a cancel request that fails at the transport level reports ERROR, so the UI marks the goal FAILED even though the server may still be running it. This is rare, and the old UI behaves the same.
- After `x`, a running goal can only be canceled by reopening its tab (`u`, or search). There is no `:cancel` yet.

## Open defects

- None for this step.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.
