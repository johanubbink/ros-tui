# Step 10 — Switch-over + cleanup: PASS

Ran:
- Before the cleanups: the full `ROS_TUI_SHOTS=1 scripts/agent_check.sh -q` (579 passed in 189 s, exit 0). flake8 found no errors; its 15 style warnings (C901, W503) are all in `ros/bridge.py`, `ros/message_yaml.py` and `test/test_bridge.py`, and none is new.
- After the cleanups: `test/ui/test_overlays.py test/ui/test_tryit.py` (15 passed), then the full suite again: 579 passed in 199 s, exit 0, with the same 15 style warnings.
- A real run in the playground container, in a pty (124×34), against `ros2 run ros_tui demo_servers`, started as `ros2 run ros_tui ros_tui --ros-args -r __node:=x`. I drove it from a throwaway script in my scratchpad:
  - The keys: `/chat` enter, space, space · `/inbox` enter, space · `/add_two` enter enter enter `19` tab `23` esc space · `/fib` enter enter enter `5` esc space · `/demo_servers` enter, `l` enter `G` `c` `odom` enter space · `4` enter `c` `40` esc space · `:q` enter.
  - On screen: `echo started`, `published`, `sum: 42`, `goal succeeded` and `set frame_id`, and no traceback.
  - The demo log has `/inbox received: ''`, `/add_two_ints: 19 + 23 = 42`, `computing order 5`, `computing order 40`, then `/fibonacci: canceled` when it quit.
  - `ros2 param get /ros_tui_demo_servers frame_id` gave `odom`, and the app exited with status 0. The `--ros-args` pass-through doesn't crash.
- `scripts/make_gif.py` in the container (with ffmpeg installed), after the fix below.

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Full suite green | PASS | 579 passed before the cleanups and 579 after them; flake8 found no errors. Shots I looked at: <ul><li>`shell/01-home`</li><li>`tryit/03-2-echo-frozen` and `13-4-repeating` (`■ Stop repeating at 5 Hz s`, `5 sent`, ↻ in the tab and the top bar)</li><li>`action/02-action-executing` (◒ in the tab, `EXECUTING 0.9 s · live feedback`)</li><li>`tryit/22-7-quat-helper`</li><li>`node/07-node-param-changed`</li><li>`tryit/35-9-keys`</li></ul>Nothing regressed apart from defect 1. The four images in `docs/images/` are byte-identical to the current shots. |
| 2 | Real demo run | PASS | See "Ran". One action on each kind of entry, a parameter set, and a running goal canceled on quit. |
| 3 | Old UI fully removed | PASS | The grep for `next_app\|NextApp\|--next\|TabbedContent\|FilterableList\|interface_tab\|WizardScreen\|step_?N\|tutorial` over `ros_tui test docs scripts README.md CHANGELOG.md` (not counting `docs/design/`) finds nothing. `export_keymap`, `test_ui_pilot` and `ctrl_t` appear only in `verification/`. `ros_tui/ui/wizards/` is gone from the disk too, and `setup.py` uses `find_packages`. |
| 4 | No dead code | PASS (after cleanups) | <ul><li>`vulture` (in a scratch venv) over `ros_tui` and `scripts`.</li><li>A grep for every module-level name, method and dataclass field in `ros_tui/` and `test/harness/` that is referenced once or not at all.</li><li>Every keymap predicate and action is used, and every action is in `nav.ACTIONS`.</li><li>A grep for every theme token.</li></ul>What it found is under "Cleanups". The test hook I kept: `RosBridge.periodic_topics()`, which `test_bridge` uses to check that stop and shutdown clear the repeats (now documented as that). `ActivityStrip.get_content_height` and `get_default_screen` are textual hooks. |
| 5 | Docs match the keymap | PASS | `test_keymap.test_the_key_tables_in_usage_md_match_the_keymap` passes. I read the README key table, `usage.md`, `architecture.md`, `testing.md`, `docker.md` and `design-principles.md`: they read as finished docs, with no steps, old UI or tutorial. |
| 6 | User decisions honoured | PASS | <ul><li>Field rows everywhere, with no YAML mode.</li><li>esc goes up one layer (`go_up`).</li><li>`.` is dropped (`test_resend_is_gone`, `test_nav`, line 539).</li><li>Only space and `^s` send (keymap rule 3).</li><li>`r` starts a repeat; in Echo it sends nothing (`test_r_in_echo_sends_nothing`).</li><li>`s` only stops or cancels.</li><li>`u` undoes per tab or reopens the closed tab, and otherwise says `nothing to undo here`.</li><li>Goals are canceled on quit (`test_bridge_shutdown_cancels_a_running_goal`, and the real run).</li><li>There is no sidebar.</li></ul>CHANGELOG lists each of them; I made "no sidebar" explicit. |
| 7 | Demo params documented as demo-only | PASS | `publish_rate` and `frame_id`: the docstring in `demo_servers.py` and its comment say nothing reads them, and so does the docker.md row. |

## Cleanups made

- `ros_tui/ui/widgets/which_key.py`: a key whose label is too long for a column gets its own line. Before, `u undo in this tab (or reopen a cl` was cut off in `?` (see defect 1). `test_overlays` now asserts the whole label.
- `scripts/make_gif.py`:
  - Frames are rendered on an opaque `BACKGROUND`, and the palette is `reserve_transparent=0`. With any transparency, ffmpeg 6.1 writes every GIF frame whole. Each frame now stores only what changed: the GIF is 4.3 MB → 763 KiB, with the same 98 frames and timings.
  - Wrapped a 132-character docstring line.
- `assets/ros-tui-demo.gif`: regenerated with that script. I looked at frames from the echo, search, action and parameter edit.
- `ros_tui/ui/theme.py`: removed the unused `faint` token. In `design-principles.md`, its row is gone and the `text` row has its real value (`#dcdcdc`, not `#c9d1d9`).
- `ros_tui/ui/nav.py`: dropped the unused `LAYERS` alias.
- `ros_tui/ui/app.py`: removed `harness_state()`, which only passed `nav.summary()` through. `test/harness/screens.py`, `agentic-dev.md` and `design-principles.md` now use `NavState.summary()`.
- `test/harness/fake_bridge.py`: removed `periodic_topics()`, which nothing calls on the fake.
- `ros_tui/ros/bridge.py`: `periodic_topics()` got a docstring saying it is for `test_bridge`.
- `ros_tui/ros/message_yaml.py`:
  - The module docstring and `FieldError` no longer speak of YAML; it is plain data ↔ message, as in architecture.md.
  - Fixed the typo `display .`.
- `docs/architecture.md`: "per-tab undo stacks" is now one undo stack whose entries are owned by tabs, which is what `NavState` has.
- `docs/design-principles.md`: added the which-key long-label rule and rewrapped two overlong lines.
- `docs/docker.md` and `ros_tui/demo/demo_servers.py`: say that the demo parameters are only there to be set.
- `CHANGELOG.md`: "there is no sidebar" is now explicit.

Reviewed and kept:
- The implementation's move of a topic's Echo / Publish mode from `EntryProvider` into `TopicData.mode`. The default provider now has no topic special case, and `DesignProvider` in `nav_world.py` stands in for the model tests.
- `MessageData.not_loaded()`.
- `entry_body.row_line` and `panel.cursor_line`, which replace the helper popup's own scroll guess with the panel's `_scrolled`.
- `nav.run_command` also accepts `:messages` and `:quit` without listing them. They are the design's aliases.

## Open defects

1. **Fixed here:** in the `?` popup, a label too long for its column was cut. It was visible in `tryit/35-9-keys` as `undo in this tab (or reopen a cl`, and predates this step.
2. None open.

## Remaining gaps (not blocking)

- The GIF's window corners are now square on `#121212` instead of rounded and transparent. That is the price of the size drop. Change `BACKGROUND` in `make_gif.py` to match a page, or revert both lines, to get them back at about 4 MB.
- The rounded popup border leaves a one-cell halo in the popup's colour outside the line (documented, not a shadow).
- `agentic-dev.md` still describes the step-by-step two-agent protocol. It is the process doc for future UI changes, so I left it.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.

## Decisions for the user

- Keep the 763 KiB GIF with square dark corners, or the 4.3 MB one with transparent rounded corners.
