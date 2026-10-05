# Step 03 — Overlays: PASS

Ran:
- `ROS_TUI_SHOTS=1 scripts/agent_check.sh test/ui/test_step03_overlays.py -q`: 5 passed before the cleanups, 12 passed after (7 new esc cases).
- `scripts/agent_check.sh -q`: 436 passed before the cleanups and 443 after. Nothing flaked this time. flake8 has nothing on the new or changed files.
- `python3 scripts/design_shots.py` on the host, for all references. The `toast` reference used to show no toast; see the cleanups.
- In the container, with the demo servers running, `python3 -m ros_tui.main --next` ran in a real pty at 124×34. Keys: nothing for 6 s, then `:foo` enter, `/` esc, `?`, then ctrl+q. There was no traceback. The output had the unknown-command toast, the search placeholder and "Keys right now". ctrl+q quit the app cleanly.

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Shot: search (`/`, `^f`) | PASS | `test_search/01-search-open` vs `design/search-open`: the box is centred at the top of the body, 84 of 124 columns (the design is 660 of 1000 px). It has the count, results grouped ≋ TOPICS … ◆ NODES, short types, the hint line, and the background veiled. `02-search-typed` vs `design/search-typed`: "pose" is highlighted in bold key colour in each name, 3 matches (the design has 4 because it includes /navigate_to_pose). `03-search-picked`: down, ^n and ^p move the cursor. `04-search-open-tab` vs `design/search-open-tab`: "open tab" on the right. `05-search-no-match`: count 0 with the empty-state line. |
| 2 | Shot: command line (`:`) | PASS | `01-command-line` vs `design/command-line`: the COMMAND badge, `:█`, and the hint on the right replace the footer. Above it, bottom left, are 7 suggestions with :log highlighted (`cmd-sel`). `02-command-suggest` vs `design/command-suggest`: one suggestion is left, and tab completes `:services`. `03-command-picked`: ↓↓↑ picks the second suggestion. |
| 3 | Shot: which-key (`?`) and the `g` popup | PASS | `01-which-key` vs `design/which-key`: bottom right above the footer, LAYERS / MOVE / GO / HELP in two columns, same rows and labels (from the keymap). `02-which-key-entry`: the entry keys, with DO (ONLY THESE SEND). `03-g-prefix` vs `design/g-prefix`: the narrow popup, gg / gt / gT, and `g…` in the footer after NORMAL. |
| 4 | Shot: toasts | PASS | `04-toast-bad` vs `design/toast`: the red toast sits bottom right of the body. `test_close_tab_toast/01-toast-info` vs `design/toast-info`: blue on `panel-in`. Both render one line without the design's 1px border. |
| 5 | Shot: `:log` | PASS | `test_log_view/01..04` vs `design/log-view`: the box over the veil, the "All activity" header with the count and hint, lines newest first in their colours, the picked line as a `cursor-on` band with `▍`, j k gg G, and enter goes to that entry's tab. The design's time column is missing (`ActivityLine` has no time yet; step 9). |
| 6 | Veil | PASS | The top bar, tab row, body and strip are at 50% under search and `:log` (the pixels measure e.g. text 136/255 and ok-green (77,113,75)), and the footer isn't dimmed, as in the design. |
| 7 | esc returns to the exact previous layer | PASS | Before, only search was checked against the full state, from inside an area. The others only checked `layer` and `path`. **New** `test_esc_returns_to_the_exact_layer[*]`: opened inside /goal_pose's MESSAGE area, in a second tab with the Topics chip on. For `/`, `^f`+typing, `:`+typing, `:` backspace, `:log`+j, `?` and `g`, it asserts that the overlay is open, then that after esc (or backspace) layer, mode, path, active, tab_cur, chip, list_cur, area and row are all equal to before. |
| 8 | Unknown commands toast | PASS | `:foo` gives `unknown command :foo — : then tab lists them` as a `bad` toast, asserted in state and on screen (`04-toast-bad`). |
| 9 | Toasts expire deterministically | PASS | `Toast.until = clock() + NAV_TOAST_S`, and `tick()` clears it. `test_toast_expires_on_the_clock` (pure model) and the scenario `advance(1.2)` (still there) then `advance(0.5)` (gone) both run on the ManualClock. `05-toast-gone`. |
| 10 | Clock and tick not wasteful | PASS | `NextApp.tick` refreshes only when `nav.tick()` returns True (a toast expired), so the 0.25 s timer is a cheap no-op otherwise. `RosBridge.now()` is `time.monotonic()`. After the cleanup nav.py no longer imports `time` at all. |
| 11 | txt / json agree with the PNGs | PASS | Spot-checked every shot. All txt and json files are byte-identical before and after the cleanups. |

## Cleanups made

- `ros_tui/ui/nav.py`: the default `NavState.clock` stands still (`lambda: 0.0`) instead of `time.monotonic`. Nav no longer reads real time anywhere, and a NavState without a bridge clock never expires toasts behind a test's back. I also dropped `import time`.
- `ros_tui/ui/widgets/base.py`: new shared `BODY_TOP`, `cursor_bar(on)` and `rule(width)`. They replace three copies of `CURSOR_BAR = '▍'` (home_list, search_popup, log_popup), two `TOP = 3` and two inline `'─' * width` rules.
- `ros_tui/ui/widgets/home_list.py`, `search_popup.py`, `log_popup.py`: these now use the helpers above.
- `ros_tui/ui/widgets/command_suggestions.py`: dropped a redundant `min(cur, len-1)` clamp, because nav already keeps `cmd.cur` in range. Named the magic `+ 5`.
- `ros_tui/ui/widgets/which_key.py`, `search_popup.py`: commented the border and padding offsets in `place()`.
- `ros_tui/ui/widgets/toast.py`: the toast width uses `cell_len`, not `len`.
- `scripts/design_shots.py`: `SETTLE_MS` 1500 → 1000. With 1500 the `toast` reference's 1.6 s toast had expired before the screenshot (it rendered without a toast every time). `design/toast.png` now shows it. The other references re-rendered fine.
- `test/ui/test_step03_overlays.py`: added the `where()` and `overlay_open()` helpers and the parametrised esc test. I also removed four assertions that were vacuous or convoluted: `state['log'] is not None`, `':services█' not in footer` (the cursor is a styled space, never `█`), `'pose' not in line_with(...)`, and the footer split/replace check. The docstring now lists all the references.
- `docs/design-principles.md`: corrected the overlay border note. The half cells outside the border are the popup's own colour, not a shadow. Added the `Overlay` / `place()` pattern under the code principles, the redraw-only-on-change tick and the standing-still default clock, and the new base helpers.

Theme tokens: the 11 new tokens are all distinct design values. `pop-edge` has the same hex as `MODES['normal']` (`#6a8fb3`). I kept them separate on purpose, because they mean different things.

## Remaining gaps (not blocking)

- There are no shadows. Popup borders sit on the popup's background, so a thin frame of the popup colour shows outside the line (an accepted approximation, now documented).
- Toasts have no 1px border in the design's darker tint, and the command line has no magenta top rule (documented).
- `:log` lines have no time column (step 9).
- `SearchPopup.place` and `WhichKeyPopup.place` build the body once to size the box, and `lines()` builds it again. The cost is negligible (fewer than 30 lines), and it keeps the sizing in one place.

## Open defects

- None for this step.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.
