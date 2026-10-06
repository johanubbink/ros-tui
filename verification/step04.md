# Step 04 — Areas + Node entry: PASS

Ran:
- `ROS_TUI_SHOTS=1 scripts/agent_check.sh test/ui/test_step04_node.py test/test_entries_node.py -q`: 42 passed before the cleanups. After them, with `test/test_nav.py` added to the run, 164 passed.
- `scripts/agent_check.sh -q` after the cleanups: 487 passed. Nothing flaked. flake8 (E, W, F, C at 127 columns) reports nothing on the new or changed files. The 28 CI-style warnings are all in old files.
- `python3 scripts/design_shots.py` on the host. I compared node-open, node-params-editing, node-param-error and node-param-changed against `test/artifacts/ui__test_step04_node__*/`.
- A real run in the container: the demo servers, then `python3 -m ros_tui.main --next` in a pty at 124×34. Keys: search `demo_servers`, then open it. Interfaces and parameters loaded (the real node has `use_sim_time` and `start_type_description_service`). I set `use_sim_time = true`, and the activity line read `✓ set use_sim_time = true`. A bad bool showed the errline. enter on an interface opened a `≋ TOPIC` tab. ctrl+q quit, with no traceback.

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Shot: area selected vs. inside | PASS | `02-node-open` and `03-node-params-selected`: the selected panel has a white border, its title is on `tab-cur`, and no row is highlighted. The other panel is at rest. `04-node-params-inside` and `11-node-interfaces-inside`: a blue border, the title on `panel-in`, and the current row on a `row-in` band with a blue `▍`. Each matches `design/node-open`. Title hints: `enter opens it in a tab` and `enter edits · space sets`, with the keys in bold white. |
| 2 | Shot: editing a param | PASS | `05-node-params-editing` vs `design/node-params-editing`: the INSERT badge, the breadcrumb `tabs › /ros_tui_demo_servers › parameters › editing`, `esc keep it` and `enter keep it`. The value is now underlined in the edit box (see the cleanups). |
| 3 | Shot: a bad value shows an errline | PASS | `06-node-param-error` vs `design/node-param-error`: the panel still says `✗ publish_rate needs a number, got "5x"` on `err-bg` at the bottom. The same line is red in the activity strip, and the layer is still insert. The errline now expires after 6 s, as in the design. |
| 4 | Shot: changed, then set | PASS | `07-node-param-changed` vs `design/node-param-changed`: `5.0` in yellow, `was 10.0` dim, and the title reads `● changed · space sets` in warn. `08-node-param-set`: `◆ /ros_tui_demo_servers ✓ set publish_rate = 5.0` in green, the marker is gone and the title is back to normal. `test_failed_set_stays_changed/01`: a rejected set leaves the change in place, with `✗ set frame_id: frame_id is read-only`. |
| 5 | u undoes only in this tab | PASS | `09-undo-elsewhere`: on /chatter, u only toasts and logs `(2 changes in other tabs are kept)`. Back on the node, u undoes (`10`). `test_undo_only_in_this_tab` and `test_undo_steps_back_through_changes` cover it too. |
| 6 | Interfaces open in a tab | PASS | `12-interface-opened`: /add_two_ints opens as tab 3 with a `⇄ SERVICE` header, REQUEST selected. Also checked in the unit test and the real run. |
| 7 | Async loading is safe | PASS | Every bridge callback only calls `post`, which is `app.post_message(UiCall(fn))`, so `fn` (the change to the model) runs on the UI thread, then the views redraw. Nothing else touches nav or the widgets from the ROS thread. `01-node-loading` shows `loading…` in both areas. Stale answers: an answer for a closed tab only fills that node's data. Reopening asks again, and the last answer wins. Changes that aren't set yet are kept, and dropped only when the parameter no longer exists. **Fixed:** a list that reloaded mid-edit could commit the typed value to a different row (or crash on a shrunk list). An edit now commits by parameter name, and the cursor is clamped to the rows there are now (`test_a_reload_keeps_the_cursor_and_the_edit_on_their_parameter`). |

## Implementer's open points: decisions

- (a) Errline expiry: **implemented**. `NAV_ERRLINE_S = 6.0`, `NavState.errlines` holds `Errline(text, until)`, `tick()` expires them, and `nav.errline(tab)` reads one. Tested in `test_errline_expires_on_the_clock`.
- (b) Undo entries for parameters that are already set: **kept as in the prototype**. The prototype's setParams doesn't drop them either. A u after a set logs "undid the change" but changes nothing visible, and the entry counts in "N changes in other tabs are kept". This is a little misleading but harmless.
- (c) Edit box legibility: **improved**. `#1c2733` on the `row-in` band (`#22303e`) was invisible in the PNG. The value is now underlined in `bright`, standing in for the design's `key` outline. Documented in the principles' stand-ins.
- (d) The YAML `10.0` vs the design's `10`: accepted. The value round-trips as a double.

## Cleanups made

- `ros_tui/ui/entries/base.py` (new): `BridgeEntry` (bridge + `post` with the run-now default) and the `Post` alias. These are the base for services, actions and topics. `NodeEntry` subclasses it, and `entries/__init__.py` no longer defines `Post`.
- `ros_tui/ui/entries/node.py`: `commit_edit` looks the parameter up by `editing.field` (new `param_named`), not by row.
- `ros_tui/ui/nav.py`: added `Errline`, `errline(tab)` and the expiry in `tick()`. `row_index` is clamped to the area's current row count.
- `ros_tui/constants.py`: added `NAV_ERRLINE_S`.
- `ros_tui/ui/widgets/node_entry.py`: removed the `running_marker` stub, which always returned an empty Text (steps 6 and 7 add it when there is something to show). The changed hint is now built with `hint(..., color='warn')` instead of a hand-assembled Text, and the errline comes from `nav.errline(tab)`.
- `ros_tui/ui/widgets/panel.py`: `hint()` takes a `color`.
- `ros_tui/ui/widgets/base.py`: `edit_value` underlines the value.
- Tests: `test/test_nav.py` has `test_errline_expires_on_the_clock`, and uses `nav.errline()`. `test/test_entries_node.py` has the reload test. The 40 pure tests were already compact (three parametrised tables plus one test per behaviour), so I left them as they are.
- `docs/design-principles.md`: errline expiry, the edit-box underline stand-in, `BridgeEntry`, edits committing by name and the clamped cursor, `tick()` expiring errlines, and the checklist now says `BridgeEntry`.

All shots are unchanged in text. The only visual change is the underline in `05-node-params-editing` and `06-node-param-error`.

## Remaining gaps (not blocking)

- A race: a parameter list asked for before a set, but answered after it, shows the old value until the next reload. This needs real-network timing, so I did not fix it.
- `EntryRouter` forwards every hook by hand: 15 one-line methods. It is explicit and easy to read, so I kept it.
- `panel_state` knows about the topic `rate` editor (as the design's `pcls`).
- The real demo node's parameters differ from the design's (no `publish_rate` or `frame_id`). Only the FakeBridge has them.

## Open defects

- None for this step.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.
