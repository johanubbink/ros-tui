# Step 09 — Cross-cutting: PASS

Ran:
- Before the cleanups: `ROS_TUI_SHOTS=1 scripts/agent_check.sh test/ui/test_step09_tryit.py test/test_register.py -q` (19 passed) and the full `scripts/agent_check.sh -q` (702 passed, exit 0). I saved every shot `.txt` as a baseline.
- After the cleanups: the touched test files (147 passed), then the full `scripts/agent_check.sh -q` again (702 passed, exit 0, nothing flaked). flake8 reports nothing new; the remaining warnings are in the old UI and `ros/` and were already there.
- `python3 scripts/design_shots.py register-copied paste-mismatch activity-strip log-view-times` on the host. I read the step 9 PNGs (at least one per try-step) next to those references.
- Shot `.txt` dumps, before vs after the cleanups:
  - Steps 0–8: identical, apart from the old UI's real-clock `response in … ms` in step 0.
  - Step 9 scenario: only the intended changes. Times after try-step 3 are 2 s later (the new `Wait(2.0)`), the paste toast is gone from 4-insert onwards, and the toast is back in 3-published (see defect 1).
- A real run in the container. I started `ros_tui.demo.demo_servers` and ran `NextApp` over a real `RosBridge` under Pilot, from a throwaway script that I deleted afterwards. The keys were `/chatter`, space, `y`, `/inbox` enter (opened in Publish), `p`, space.
  - The register held `{'data': 'chatter 7'}`.
  - The toasts said `copied the latest String from /chatter`, then `pasted from /chatter · u undoes`.
  - The demo server logged `/inbox received: 'chatter 7'`.
  - The activity lines showed real local times (`12:20:24 /inbox ✓ published · data: chatter 7`, `12:20:20 /chatter ◉ echo started`).

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Try-steps 1–9 end to end | PASS | `test_try_steps_1_to_9`: 35 shots in `ui__test_step09_tryit__test_try_steps_1_to_9/`. Each checks the footer (mode, breadcrumb, active tab), the toast where it matters and the screen. `test_the_steps_cover_try_steps_1_to_9` checks that every try-step is covered. |
| 2 | User decisions | PASS | <ul><li>No `.` key anywhere: `test_keymap.test_resend_is_gone`, and `.` only logs a hint (`test_nav`). Step 5 uses `[ ]`.</li><li>`r` in Echo sends nothing (`test_r_in_echo_sends_nothing`).</li><li>`s` only stops or cancels (8-goal-canceled).</li><li>`u` on nothing says `nothing to undo here` (`test_p_refuses_another_type`, `test_p_pastes_the_same_type_as_one_undo_step`).</li><li>There is no tutorial or `steps.json`.</li></ul> |
| 3 | Typed register | PASS | `04-2-copied` vs `design/register-copied`: the magenta chip `copied: String from /chatter · p pastes` after the search hint, and the toast `copied the frozen String from /chatter`. Pasting into /inbox is one undo step (`07`/`08`). `paste-mismatch` vs `design/paste-mismatch`: the red toast `copied a String, this needs a PoseStamped`, and the message is unchanged. Roles are covered too (`AddTwoInts request` vs `goal`). The decided copies are in place: `nothing to paste into on a node`, and `… it was the same already` with no undo step. |
| 4 | Frozen copy is exact | PASS | The scenario copies `chatter 3` while frozen, although `chatter 5` is the newest. `test_y_copies_the_message_exactly_not_as_it_is_shown` is meaningful: <ul><li>`position.x == 2.0*cos(0.5)` to full precision, where the echo shows 6 digits.</li><li>A 300-character string is copied uncut, where the display cuts it at `TRUNCATE_STRING_CHARS`.</li></ul> |
| 5 | Activity strip: times, dim, fresh | PASS | `09-3-published` vs `design/activity-strip`: `09:41:05 ≋ /inbox ✓ published …` on a green band with a `▍` bar. The `/chatter` line is dimmed (another tab). `15-5-called-again` has three fresh lines. In `18-6-activity` the highlight has faded. Times come from `bridge.time_of_day()`. |
| 6 | `:log` | PASS | `19-6-log` vs `design/log-view-times`: `All activity 7 entries, newest first · j k move · enter goes there · esc closes`, with the time, glyph, entry and text on every line. `G` picks the oldest line, and `enter` jumps to /chatter (`20-6-log-jump`). It uses the same `activity_row` as the strip, so the formatting isn't duplicated. |
| 7 | Flash on send | PASS (changed) | The primary button now turns a lighter blue for 0.5 s (`09-3-published`, `15-5-called-again`). The flash happens only where something goes out: publish once, call, send goal. `test_a_send_flashes_the_primary_button_for_half_a_second`, `test_only_a_send_that_goes_out_flashes`. |
| 8 | Redraw budget | PASS | A fade costs exactly one redraw (`test_a_new_activity_line_is_fresh_for_a_while` asserts `tick() and not tick()` at the fade). An idle app never redraws (`test_entries_topic`). Before the cleanup, adding a line also cost a second, extra redraw. |

## Cleanups made

- `ros_tui/ui/entries/topic.py`: `latest`/`shown` and `latest_raw`/`shown_raw` (four fields) are now two `Received(message, display)` fields. The new `received()` picks frozen or newest for both the echo rows and `y`, so that choice is made in one place.
- `ros_tui/ui/entries/topic.py` and `entries/node.py`: removed `flash_send` from echo start/stop (nothing is sent to the robot) and from node set (no button to flash; it only cost a redraw).
- `ros_tui/ui/widgets/base.py`: the `flash` look is `bright` on `accent` (a lighter blue). It was black on white. My call: the white fill read as an inverted, different control and was the loudest thing on screen.
- `ros_tui/ui/nav.py`: `tick()` redraws only when the fresh count falls. Whatever adds a line already redraws.
- `ros_tui/ui/next_app.py`: a `Body` container re-places the overlays when it resizes. This fixes defect 1 below.
- `test/ui/test_step09_tryit.py`:
  - Clock advances are `Wait(seconds)` instead of bare floats in the key lists.
  - Removed a stray `' '` string concatenation.
  - Added a `Wait(2.0)` before try-step 4, so the paste toast has expired as it would in real time.
- `test/test_register.py`: the fade test now really asserts one redraw. The flash test also checks that starting an echo doesn't flash.
- `test/test_entries_topic.py`: corrected a comment that still mentioned the flash.
- `docs/design-principles.md`:
  - The flash rule: what flashes, why it isn't white, and that echo and node don't flash.
  - The `Received` naming.
  - The fade-only redraw rule.
  - Overlays are re-placed when the body resizes.

Reviewed and kept:
- `register.py` is pure and small: `Register.of` (deep copy), `label`, `chip`, `mismatch`.
- `MessageEntry.yank`/`paste` and `_loaded_editor`.
- `ActivityLine.time` and `at`, and `clock_text`.
- `bridge.time_of_day`, and the 09:41:00 base in `FakeBridge`.
- `primary_look`.

## Open defects

1. **Fixed here (it predates this step, and this step's cleanup exposed it):** the toast is placed from the body's size as it was before layout. When the activity strip grew a line, the body shrank and the toast sat one row below it, so it was invisible. Before the cleanup, the extra "fresh count rose" redraw hid this within 0.1 s. Now `Body.on_resize` re-places the overlays.
2. None open.

## Remaining gaps (not blocking)

- The `6-activity` shot has only `/add_two_ints` lines, so the dimming is shown by `09-3-published` (the /chatter line) rather than by that shot.
- The selected row in `:log` shows its time in `dim` on the cursor band, so the time is faint. The design does the same.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.

## Decisions for the user

- The flash is a lighter blue fill instead of the white fill the implementation used. It's easy to revert: change the `flash` row in `BUTTON_LOOKS`.
- Starting or stopping an echo no longer flashes the button. The design flashes on every primary action; I followed the rule "flash only when something is sent".
