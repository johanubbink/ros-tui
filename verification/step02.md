# Step 02 — App shell: PASS

Ran:
- `ROS_TUI_SHOTS=1 scripts/agent_check.sh test/ui/test_step02_shell.py -q`: 8 passed, before and after the cleanups.
- `scripts/agent_check.sh -q`: 427 passed before the cleanups (419 other tests + 8 in step 2). After the cleanups, one run had 2 old-UI failures (see open defects). `test/test_ui_pilot.py` alone then passed 92 of 92, and a second full run passed 427 of 427. flake8 has nothing on the new files.
- `python3 scripts/design_shots.py home chatter-open topic-chip tab-row many-tabs many-tabs-start` on the host. I compared each design shot with its app shot by eye.
- In the container, with the demo servers running, `python3 -m ros_tui.main --next` ran in a real pty at 124×34 for 6 s, then enter, then the timeout ended it. There was no traceback. The ☰ list filled from the real graph, and /chatter opened in Echo (LATEST MESSAGE), so the real publisher count got through. `python3 -m ros_tui.main --ros-args -r __ns:=/x` started the old four-tab app, and `--ros-args` still passes through.

## Criteria

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| Shot: home | PASS | `01-home` vs `design/home`: chips with counts, the ☰ tab underlined in accent-fill, groups `≋ TOPICS · 6` … `◆ NODES · 2`, Name / Type / Here, cursor row on /chatter. The demo world has 11 entries and the design has 12 (it adds /navigate_to_pose); that's expected. |
| Shot: topic chip | PASS | `02-topic-chip`: the tab reads `☰ Topics`, the Topics chip is on, only the 6 topics are listed. |
| Shot: tab open | PASS | `03-chatter-open`: tab 1 is active and underlined in the topic tint. Header `≋ TOPIC /chatter std_msgs/msg/String` with Echo on. The selected panel has a white border and a `#262b33` title. `04-inside-area` shows the blue border. |
| Shot: tab-row layer | PASS | `05-tab-row`: the cursor outlines tab 1 with `▏ ▕` in the key colour, and the footer shows only `tabs`, `enter go in` and no esc. `06-tab-row-home`: the cursor is on ☰. |
| Shot: overflow with 10 tabs | PASS | `07-many-tabs`: `‹ 6 more` on the left and the active tab 10 (◆, no number) in view. `08-many-tabs-start`: cursor on ☰, `5 more ›` on the right. Both match the design's behaviour. `fit_tabs` has its own unit cases. |
| Breadcrumb + mode badge on every layer | PASS | Asserted on the txt dumps and in the JSON state: `tabs › ☰ list` / esc tab row / enter open /chatter, `tabs › /chatter` / enter into latest message, `tabs › /chatter › latest message` / esc back out / enter show / hide field, `tabs` / enter go in. The NORMAL badge is `#6a8fb3`. The JSON `state` agrees with the PNGs and txt files. |
| No sidebar, full width | PASS | Every view spans the full 124 columns. Nothing else takes width. |
| Keys reach nav, widgets never take focus | PASS | `app.focused is None` throughout. tab doesn't move focus (it switches the chip), ctrl+p doesn't open the palette, and the screen stack stays at 1. **New in the test:** space and ctrl+s reach the primary verb (logged as `space` / `^s`), `/` + `c` opens search with `c`, esc closes it, `?` opens which-key, any key closes it, and `:q` + enter quits. |
| Old app still default and working | PASS | `main.py` runs `RosTuiApp` unless `--next` is given. Its tests are green, and it started in the container. |
| Publisher counts not wasteful | PASS (after fix) | See cleanups. |

## Cleanups made

- `ros_tui/ui/next_app.py`: each `PublisherCount` used to rebuild the whole catalogue and redraw, which is O(topics²) per graph change. A burst of counts now marks the catalogue dirty and rebuilds it once (`call_later(_apply_publishers)`). Asking per topic only on a graph change is kept on purpose: `_poll_graph` only fires when names or types change, so asking only for new topics would leave counts stale when a node with publishers starts on a known topic.
- `ros_tui/ui/next_app.py`: I shortened the module docstring.
- `ros_tui/ui/widgets/tab_row.py`: dropped the `TOKENS['accent-fill']` lookup and the `TOKENS` import. `style()` already resolves token names.
- `ros_tui/ui/widgets/entry_body.py`: Node panels are now split 10:11 (the design's flex 1 / 1.1), where they were split equally. I also dropped a redundant padding background in `panel()`, which the stylize right after already set.
- `ros_tui/ui/widgets/activity_strip.py`: the inline `{'r': 'bad', 'g': 'ok'}` is now the module constant `LINE_COLORS`.
- `ros_tui/ui/theme.py`: the `rule` comment said it was used above the activity strip. It isn't.
- `test/ui/test_step02_shell.py`: `test_quit_and_textual_keys` now also checks that space, ctrl+s, `/`, `?` and `:` reach the model.
- `docs/design-principles.md`: the theme block (`theme.py`, `$rt-*`) and the single `on_key` router are now marked as current. Added the `NavView` render pattern, and a new "Terminal approximations" section: tab underline row, tab-row cursor edges, list cursor bar, chip / switch blocks, panels, overflow markers, and the omitted 1px rules.

Shots after the cleanups: all txt dumps are byte-identical except `07-many-tabs` and `08-many-tabs-start`, where only the Node panel split changed (intended). Some SVGs differ only in how rich splits the background spans of the panel padding.

The code is in good shape as handed over. The widgets are thin: they read `NavState`/`footer()` and keep only scroll offsets. The text helpers are shared in `widgets/base.py`, and there are no hex colours outside `theme.py`. I found no dead code beyond `TopBar.running()`, a deliberate stub for step 6.

## Visual gaps remaining (not blocking, all for later steps or accepted approximations)

- Toasts aren't drawn: `closed /counter · u undoes` is in the state but not on screen. That's step 3, along with the overlays.
- Activity lines have no time column, because `ActivityLine` has no time yet (step 9).
- The topic header lacks `1 pub · 0 sub`. The count future returns (pub, sub), but only pub is kept (step 6).
- The entry body is a placeholder. There's no button row under the header (Start echo / Publish once), and placeholder text runs right up to a narrow panel's right border.
- The 1px rules above the activity strip and the footer are left out, now written down as an approximation.
- The list cursor is a `▍` bar plus background, and chips are background blocks rather than rounded pills. Both are written down as approximations.

## Open defects / notes

- Flaky old-UI tests: `test/test_ui_pilot.py::test_publisher_leaf_jumps_to_topics_tab` (known), and this time also `test_selecting_node_shows_interfaces_and_params`. Both failed once in a slower full run (175 s against 110–130 s) and passed when rerun alone and in the next full run. That's old-UI code, which step 2 doesn't touch, so it's probably a Pilot timing race. It goes away at step 10.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.
