# Step 05 — Field-row editor + Service entry: PASS

Ran:
- `ROS_TUI_SHOTS=1 scripts/agent_check.sh test/ui/test_step05_service.py test/test_fields.py test/test_entries_service.py -q`: 84 passed, before the cleanups.
- `scripts/agent_check.sh -q` after the cleanups, twice: 573 passed both times, and nothing flaked. flake8 reports nothing on the new or changed files. The remaining CI-style warnings are all in old code (`message_yaml._build`, the wizards, the old tests).
- `python3 scripts/design_shots.py` on the host. I compared service-open, service-editing, service-called, service-error and service-history with `test/artifacts/ui__test_step05_service__*/`.
- I diffed the shot text dumps of steps 4 and 5 between the two full runs after the cleanups, and they are identical.
- A real run in the container: `ros_tui.demo.demo_servers`, then `NextApp` over a real `RosBridge` under Pilot (a throwaway script, since deleted).
  - /add_two_ints with a=19 and b=23 gave `✓ OK 12.0 ms` and `sum: 42`, with both activity lines.
  - /set_pose with x=3 and y=4 gave `✓ OK` and `empty response (no fields)`.

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Shot: edit | PASS | `02-service-editing` vs `design/service-editing`: the INSERT badge, the breadcrumb `tabs › /add_two_ints › request › editing`, `19` underlined in the edit box with a cursor, and `esc keep it` / `enter keep it`. |
| 2 | Shot: invalid value | PASS | `05-service-error` vs `design/service-error`: still in insert with `abc`. The red errline `✗ a needs a whole number, got "abc"` is at the bottom of REQUEST, and the same line is red in ACTIVITY. |
| 3 | Shot: call | PASS | `03-service-calling`: a cyan `calling…` pill and `waiting for the response…`, with `▶ called · a: 19, b: 23` in ACTIVITY. |
| 4 | Shot: response | PASS | `04-service-called` vs `design/service-called`: a green `✓ OK` pill, then `50.0 ms` (deterministic from the fake clock), then `1  sum: 42  # int64`. The REQUEST title reads `[ ] history (1) · i edit · p paste`. The activity lines match the design. `service-failed`: a red `✗ FAILED` pill, the time, and the errline `✗ call failed: …`. `set-pose-called`: an empty response. |
| 5 | Shot: history step | PASS | `06-service-history` vs `design/service-history`: `[ ] history #2/2` with `a: 19`. `07-service-draft`: `] ]` brings back the draft (`a: 7`) and `history (2)`. |
| 6 | Every field reachable by keyboard | PASS | `test_every_leaf_of_a_nested_request_is_reached_and_edited_by_keys` walks the whole of SetCameraInfo with j, l and o, and edits every row that can be typed. It now edits with `i`, because enter folds a list (see the fix below). `nested-*` shots: `▾`/`▸` and the two-space indentation are readable. The glyphs are small in JetBrains Mono, but the row numbers and the indentation carry the structure. |
| 7 | Round-trip over every type in `test_message_yaml` | PASS | `test_rows_round_trip` is parametrised over `ROUNDTRIP_TYPES`. It goes rows → dict → rows, retypes every editable row's own text with no change, and the values build. |
| 8 | esc semantics kept | PASS | esc goes up one layer from any depth of row (`test_fold_and_unfold_keys`). In insert, esc keeps a valid value and drops a bad one with a toast (`test_a_bad_value_stays_in_insert_and_esc_drops_it`). Folding has its own keys. |
| 9 | Nothing sends except space / ^s | PASS | `service_calls == []` after edits, tab and esc. ^s in insert keeps the value and calls (`test_ctrl_s_in_insert_keeps_the_value_and_calls`). `.` is not bound (the user's decision). |
| 10 | Threading | PASS | Types are imported in `NextApp._work`, a textual thread worker (`exit_on_error=False`), and the result comes back through `_post` → `UiCall`. `on_open` doesn't load twice while a load is running (tested). Results go to `self._data[tab.key]`, which lives across close and reopen, so a late answer fills the same entry and can't land on another one. Call futures resolve on the ROS thread. `_answered` only reads the clock and makes the response plain data there, then posts `_call_done`. Only one call runs per service. RosBridge times out calls with no server, so `calling…` can't hang forever. |

## Keymap review

- **h / l per layer.** In the IN layer, `h j k l` pick an area. In the AREA layer on field rows, `j k` move and `h l` fold, unfold, go up to the parent or step in, the way a file tree does (ranger, nvim-tree). On non-field areas, such as node parameters, h and l do nothing. This is predictable per layer, and it is documented in the layer table (row 3), the field-row section and the keymap labels.
- **`o` / `d`.** These don't clash with any key in the prototype (y p u x e f r R s [ ] i a c gg G H L) or with any planned key. They only apply to `area fields editable`, so they never fire on RESPONSE.
- **The footer's enter label.** On a row that folds it says `unfold` or `fold`. **Fixed:** on a list of numbers (e.g. `k [9 items]`) it said `unfold`, but enter edited the whole list. `NavState.activate_row` now tries the provider's own row action (fold, open an interface) before editing, so enter always does what the label says, and `i` / `c` type the whole list. Test: `test_enter_folds_a_list_and_i_types_it_whole`.

## The implementer's extras: my judgement

- **"Fresh" zero numbers** (the first key replaces a `0` value): **kept.** There is no cursor movement in insert, so without it you would type `019` or `0.05`. It is consistent with bool (fresh since step 4) and with the design's enum fresh. Compact rows are not fresh, which is right.
- **Typing a whole list of numbers or strings on its row:** **kept.** It is far quicker for `double[9]` or `double[36]` than nine edits, and it stays reachable by tab. It was inconsistent with enter until the fix above.
- **The node change, outside the step's scope:** a set parameter now drops its undo entries, so `u` no longer logs a no-op "undid". This reverses step 4's decision (b), and it is an improvement. `test_step04_node` was adjusted for it.

## Cleanups made

- `ros_tui/ui/nav.py`: `activate_row` runs the provider's row action before `start_edit` (the enter-label fix above). The `EntryProvider.activate_row` docstring says so.
- `ros_tui/ui/fields.py`:
  - Removed the unused `INT_TYPES`.
  - Removed `HELPERS` and `Row.helper`. They were speculative and step 8 owns field helpers. The widget still marks where the `[f …]` badge goes.
  - `accept` no longer builds a throwaway `FieldRows` to set a value. It now uses the pure `_get` / `_put` path helpers, which `get` uses too, and `FieldRows.set` is gone.
  - `describe` is now flat ifs instead of a nested conditional expression.
  - Parenthesised the `fresh` expression.
- `ros_tui/ros/message_yaml.py`: `message_structure` now reuses `class_structure`.
- `ros_tui/ui/entries/service.py`: removed the `data()` override, which only re-declared the return type.
- `ros_tui/ui/keymap.py`: parenthesised the `fields` predicate (`a or (b and c)`).
- `ros_tui/ui/widgets/field_rows.py`: the step-8 comment no longer names the removed `row.helper`.
- Tests:
  - `test_fields.py`: one `leaf_row(label)` helper, built on `fields.Element`, replaces the `_Node` class and the duplicated row construction.
  - `test_entries_service.py`: the reachability walk edits with `i`, and the new test `test_enter_folds_a_list_and_i_types_it_whole` covers the fix.
  - The other tests were already compact, mostly one behaviour per test or parametrised tables, so I kept them.
- `docs/design-principles.md`:
  - enter always matches its footer label, and `i` / `c` type a whole list.
  - tab in insert skips nested messages and lists of messages, but not lists of numbers.
  - `activate_row` runs before editing.

## Remaining gaps (not blocking)

- The design's `. resends` hint is gone, by the user's decision. The plan's Step 5 row still mentions `.`.
- Two text parsers: `entries/node.parse_value` (parameter types) and `fields._scalar` (IDL types) word their errors the same way, but they differ in detail (`5.0` counts as a whole number only in fields, and node strings are not unquoted). They could be merged when the node editor moves onto field rows, if it ever does.
- `FieldRows` assumes the plain values hold every field (they come from `message_to_plain`). A partial dict would only fail when editing a nested field that is missing.
- `MessageEntry` has no `helper_name` yet (step 8), so the footer doesn't show `f` on field rows.
- The demo `TEMPL` values in the design (a 19, b 23) differ from the real zero defaults. As expected.
- The real RosBridge timing (`12.0 ms`) looks coarse. It comes from `bridge.now()`, not from this step's code.

## Open defects

- None for this step.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.
