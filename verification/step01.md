# Step 01 — Nav model + keymap: PASS

Ran:
- `scripts/agent_check.sh test/test_nav.py test/test_keymap.py -q`: 163 passed before the cleanups, 173 after (10 new tests)
- `scripts/agent_check.sh -q`: 409 passed before the cleanups, 419 after (see the flaky old-UI test under open defects). The flake8 error pass is clean, and the style pass shows the same 28 pre-existing findings, none of them in the new files.

## Criteria

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| Every key in the prototype's `keyList()` is in `keymap.py` with the same label, minus `.` | PASS | `test_every_design_key_is_in_the_table` parses every literal row of `keyList()`. The 13 computed rows are in `DYNAMIC_ROWS`. `test_resend_is_gone` checks that `.` is in the design but not in the table. I compared the group, key and label of each row by hand as well. |
| Send rule (space / ^s send, `r` repeats, `s` only stops) | PASS | Only space and ctrl+s dispatch `primary` (in insert, only ctrl+s). The SEND group lists only space. `.` gives a hint (`test_full_stop_does_nothing`). |
| No textual / rclpy / rich import in nav.py / keymap.py | PASS | `test_pure_python` runs the imports in a subprocess and checks `sys.modules`. |
| At least 20 scripted transitions match the prototype | PASS | There are 56 `SEQUENCES` and about 50 focused tests. I checked about 15 tricky cases against the prototype code (below). |
| docs/design-principles.md accurate | PASS (after edits) | It covers the send rule, the keymap table, the provider and the router. I added how `ACTIONS` dispatch works and corrected what the default provider does. |

### Sequences checked against the prototype (by reading both)

These already matched: the tab-row cursor wrap through ☰ at -1 (`tabCur>=n-1?-1:+1`), including with zero tabs; x on the last tab or the only tab (`active=min(i,len-1)`); x then u from the tab-row layer (reopens at the same index, layer `in`); `/` then esc inside an area (layer unchanged); `:ra` + enter (stays open as `rate `) against `:rate` + enter (runs with no argument); g then esc (`g canceled`, the layer is kept); `?` then any key (only closes the popup); a digit with no tab behind it (`no tab N`); H/L from the tab row (steps from `active`, not from the cursor, and goes in); G/gg on each layer; enter or esc on a bad value (`bad()`: esc drops it, enter stays with an errline); tab in insert only for `msg` rows; `f` on a picked message area goes into the area first; the per-tab undo owner rule and its "N changes in other tabs are kept" text.

New tests for the gaps: x on the only tab, u after x on the tab row, H from the tab row, a digit with no tabs, `?` then x, g esc in an area, `:` esc in an area, the tab-row cursor with no tabs, the gt/L log text, `:rate` without its argument against `:ra`, and the command line opening empty each time.

## Cleanups made

- `ros_tui/ui/nav.py`: I kept `ACTIONS` as a flat dispatch table and made each entry one call. The tuple-of-`setattr` lambdas became methods: `g_prefix`, `helper_close` and `cmd_backspace`. Named methods for every action would have doubled the method count and added nothing.
- `ros_tui/ui/nav.py`: 4 actions became 2. `edit_from_in`, `clear_from_in`, `edit` and `clear_edit` are now `edit` and `clear`, both through one `edit_row(how, clear)` that restores the layer it started on.
- `ros_tui/ui/nav.py`: in g mode, `handle_key` now builds `how` as `'g' + key`. This removed the `'gt' if p.key == 't'` hack in `tab_next/prev` and the hard-coded `'gg'` in `move_top`.
- `ros_tui/ui/nav.py`: `_overlay`, `list_mode`, `input_mode` and `mode_name` were collapsed. `list_mode` is now the only overlay chain, and the other two derive from it.
- `ros_tui/ui/nav.py`: added `_cycle` (wrap through -1) and `_clamp`. They replace the three hand-written wrap blocks (tab cursor, chip, `step_tab`) and six clamps.
- `ros_tui/ui/nav.py`: removed `KIND_LABELS`. Its only use was `.lower()` on the label, which gives back the kind itself.
- `ros_tui/ui/nav.py`: renamed the search and log methods to match their action prefixes (`search_open/close/step/edit`, `log_goto`). `step_log(None)` for G was replaced with `log_goto(index)`.
- `ros_tui/ui/nav.py`: `label_vars` is now a single dict expression.
- `ros_tui/ui/keymap.py`: renamed the actions as above. shift+tab now completes on the command line too: the prototype's `e.key` is `Tab` for both.
- `test/test_nav.py`: added the 10 gap tests and dropped `test_footer_modes`, which the sequences and `test_edit_and_keep` already cover.
- `docs/design-principles.md`: added a router / `ACTIONS` bullet, and corrected what the default provider does (it handles `e` and `f`, and logs "not built yet" for the other verbs).

While cleaning up I caught one bug in my own first pass: `_set('cmd', CommandLine())` would have shared one mutable instance. `cmd_open` builds a new one each time, and `test_command_line_opens_empty_each_time` guards it.

## EntryProvider review

The hooks are `on_open`, `mode`, `screen`, `areas`, `row_count`, `start_edit`, `commit_edit`, `activate_row`, `leave_area`, `esc_label`, `helper_name`, `label_vars`, `verb` and `undo`. Each one maps to a prototype function that a later step needs:
- `leave_area` and `esc_label` are the frozen echo's "go live" (step 6).
- `helper_name` is `helperAt` (step 8).
- `activate_row` is ifs/out (steps 4 and 6).

None is unused by design, so I kept them all. `verb(name, …)` with string names keeps the protocol small. Note that `NavState` holds a single provider, so step 2 or 4 will need a provider that dispatches per kind. The plan's "subclass per kind" works on top of that. I didn't build it now.

## Deviations

- (2) On an empty `:` line, ↑↓ then enter runs the picked suggestion. The prototype needs typed text before it substitutes a pick. **Accepted**: picking and pressing enter means run it.
- (3) `:q` sets `nav.quit` where the prototype toasts "would quit". **Accepted**: the app acts on it.
- (6) `area_index` is clamped to the screen's areas. **Accepted**: it's a harmless guard, because the index is stored per screen.
- (new, mine) shift+tab completes on the command line, matching the prototype (see above).

## Open defects / notes (none blocking)

- `p` with no entry open logs "open an entry first". The prototype toasts "nothing copied yet (y copies)". The register arrives in step 9, so revisit it there.
- The hint for an unused space reads `nothing on "space" here`, where the prototype prints `" "`. It's cosmetic.
- An untracked `ros_tui Hybrid Keys(6).html` sits in the repo root. Its `keyList()` is identical to `docs/design/hybrid-keys.html`. Don't commit it.
- `test/test_ui_pilot.py::test_publisher_leaf_jumps_to_topics_tab` is **flaky**: 2 of 5 full runs failed with `'nodes' == 'topics'`, and the other 3 were green. It is old-UI code and doesn't import nav.py or keymap.py, so it isn't caused by this step. It is probably a Pilot timing race. That test goes away at step 10; make it more robust or mark it before then if it bothers CI.
