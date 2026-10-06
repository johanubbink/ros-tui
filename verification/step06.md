# Step 06 — Topic entry: PASS

Ran:
- `ROS_TUI_SHOTS=1 scripts/agent_check.sh test/ui/test_step06_topic.py test/test_entries_topic.py -q`: 41 passed, before the cleanups.
- After the cleanups: the step's tests with fields, nav, node and service, 298 passed. Then the full `scripts/agent_check.sh -q` twice, exit 0 both times, the second with `626 passed`. Nothing flaked. flake8 found no errors, and its 28 style warnings are all in old code (wizards, `message_yaml`, old tests).
- I diffed the step 4–6 shot text dumps between the two full runs, and they are identical. Compared with before the cleanups, only `echo-pose` changed, and that was intended: the floats are now readable.
- `python3 scripts/design_shots.py` on the host. I compared chatter-open, echo-live, echo-frozen, publish-open, publish-repeating and rate-editing with `test/artifacts/ui__test_step06_topic__*/`.
- A real run in the container: `ros_tui.demo.demo_servers` plus `NextApp` over a real `RosBridge` under Pilot, from a throwaway script (since deleted):
  - **/chatter** opens in Echo (`1 pub · 0 sub`): 3 received at 1.0 Hz.
  - **/counter**: 132 received at 50.0 Hz with 0 dropped. Over 2 s there were 20 ticks and 22 `message_to_display` calls (about one per tick), and 20 redraws.
  - **/inbox** opens in Publish:
    - The publish once and the repeat were both received by the demo server (`/inbox received: 'hello real'`).
    - `R 5` restarted the running repeat at 5 Hz.
    - `s` stopped it: `periodic_topics()` went to `()`.
  - I restarted the repeat and quit with `:q` while it ran. The server's receive count stayed the same over the next 2 s, so the repeat stopped on quit.
  - **Redraws on the tick:** none when idle (1 s: 10 ticks, 0 redraws) and none with two echoes running behind the ☰ list.

## Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Shot: echo live | PASS | `02-echo-live` vs `design/echo-live`: orange `■ Stop echo space`, then `3 received · 1.0 Hz`; `LATEST MESSAGE ● live · enter freezes it`; `[x] data 'chatter 3'`; a cyan ◉ in the tab and `≋ ◉ /chatter` in the top bar. |
| 2 | Shot: echo frozen | PASS | `03-echo-frozen` vs `design/echo-frozen`: blue border, the `❄ FROZEN` pill, `+3 new since` in warn, the value stays `'chatter 3'`, and the footer says `esc go live` and `enter show / hide field`. `04-echo-hidden`: `[ ] data  hidden`. `05-echo-live-again`: `'chatter 6'`. |
| 3 | Shot: publish / repeat | PASS | `01-publish-open` vs `design/publish-open`: a blue (`pri`) Publish button and a grey Repeat button with `10` underlined, then `default · R changes it`. `05-publish-repeating` vs `design/publish-repeating`: the stop look, `■ Stop repeating at 5 Hz s`, `your rate · R changes it` and `10 sent` in green. |
| 4 | Rate edit inline + errline | PASS | `03-rate-editing` vs `design/rate-editing`: the edit box sits in the button, with `type a rate · enter keeps · 0.1–100 Hz`, no panel highlighted, and the footer `INSERT … repeat rate › editing`. `04-rate-error`: the errline `✗ rate must be 0.1–100 Hz, got "500"`, also in ACTIVITY. |
| 5 | The rate applies to a running repeat | PASS | Unit test `test_a_new_rate_restarts_a_running_repeat`: it restarts at 5 Hz, `↻ rate now 5 Hz`, then 15 sent after 1 s + 1 s, and undo restarts it at 10 Hz. The scenario does the same with `:rate 2` and `u`. The real run did it with `R 5` against the demo server. |
| 6 | The echo drain stays bounded | PASS | `EchoBuffer` drops the oldest past `ECHO_BUFFER_MAXLEN`. Each tick converts only the newest message. Real run at 50 Hz: about one conversion per tick. `test_the_echo_drain_keeps_only_the_newest_message`. |
| 7 | Running markers everywhere | PASS | The tab shows `/chatter ◉` and `/inbox ↻`, the top bar `≋ ◉ /chatter  ≋ ◉ /counter`, and the Here column `◉ echoing open` and `↻ 5 Hz open` (`06-home-*`). Search rows use the same `markers()`. |
| 8 | Default mode, `e`, "waiting — nobody publishes" | PASS | /chatter opens in Echo and /inbox in Publish. `e` and `:echo` / `:pub` switch modes and keep the message. `07-echo-nobody`. |
| 9 | Only space / ^s send; r starts, s stops | PASS | `r` in Echo only says `r repeats a publish — e switches to Publish`. `r` while repeating only shows a toast. `s` never sends. These are the decisions already taken, and I kept them. |
| 10 | Nested echo readable | PASS (after fix) | `echo-pose`: one row per path, with compact rows on one line. Floats were full-precision noise (`1.0806046117362795`) and now show `{x: 1.0806, y: 1.68294, z: 0.0}`. |
| 11 | Performance: idle tick | PASS (after fix) | The 0.1 s tick already did no work when idle. But any running repeat redrew every tick, and so did an echo in a hidden tab. Now a redraw happens only when the active tab shows something new. Test: `test_the_tick_redraws_only_when_the_active_tab_shows_something_new`. |
| 12 | Threading | PASS | Subscription callbacks only `push` into `EchoBuffer` on the ROS thread, and only the UI tick drains it. The counts and the failed subscribe, publish and repeat futures go through `_post`. Echoes and repeats keep running across tab switches. |

## Decisions applied

- **Display rounding**, which I implemented: `fields.readable` cuts floats to `ECHO_DISPLAY_DIGITS = 6` significant digits and never cuts the whole part. It applies only in `flat_text`, so the row values (`data.latest` / `shown`) stay exact.
- **Echo or repeat on tab close:** I kept the design's behaviour, where both keep running. It is never invisible: the top bar and the Here column show it. Quitting stops everything (`bridge.shutdown`), as the real run confirmed. This is documented.
- I kept `r` in Echo, `r` while repeating, and stop clearing the values to `–`. I didn't touch undo, which is step 7.

## Cleanups made

- `ros_tui/ui/fields.py`: `readable()`, and `flat_text` uses it (strings keep the row's quoted text).
- `ros_tui/constants.py`: `ECHO_DISPLAY_DIGITS`.
- `ros_tui/ui/entries/topic.py`: `tick` redraws only on a visible change of the active tab, through the new `TopicData.seen`. It is no longer unconditional while a repeat runs or for an echo in a hidden tab.
- `ros_tui/ui/nav.py`: `Tab.of(key)` replaces five copies of `Tab(*key.split(':', 1))` in node, message and topic. The router keeps its own split, because an owner can be `*`.
- `ros_tui/ui/widgets/topic_entry.py`: `echo_toolbar(data, width)` dropped three unused parameters.
- Tests:
  - `test_entries_topic.py`: added the rounding table, a test that the echo shows readable floats but keeps the exact value, and the tick-redraw test.
  - `test_step06_topic.py`: asserts the readable pose, and its `expect` text now says so.
- `docs/design-principles.md`: added the rounding rule, the echo and repeat behaviour on tab close and on quit, redraw-only-on-visible-change, `Tab.of`, and the default provider's "for topics" fallbacks.

I reviewed and kept:
- `editor_panel`, shared by service and topic.
- `button()` and `markers()` in `base.py`.
- The `running` / `tick` provider hooks, which are minimal.
- The `Commit.activity` field.
- The fake bridge's `periodic_sent`, which the unit tests use.
- The default provider's `repeat` / `rate` / `set_rate` fallback for non-topic tabs. It sits alongside the existing `toggle_mode` "only topics have Echo / Publish", in the provider that already owns a topic's mode, so it isn't new leakage.

## Remaining gaps (not blocking)

- **Step 9 copy:** `data.latest` holds the floats exactly, but it comes from `message_to_display`, so arrays past 16 elements and strings past 256 characters are already cut. To copy exactly, step 9 should keep the newest (and frozen) raw message.
- The Echo / Publish mode still lives in the default `EntryProvider`, which the nav unit tests use over the design world. It could move into `TopicEntry` if `nav_world` gets a topic provider.
- `N sent` is computed from the clock. Against real timers it can differ from the actual count by about 1 (in the real run, the UI said 19).
- After `u` on a rate, the earlier `:rate` toast (`repeat rate 2 Hz`) still shows until it expires (visible in `06-home-repeating`). The prototype behaves the same, since undo only logs.
- The ☰ list keeps `0 pub` for a topic the UI repeats on until the graph refreshes.
- The echo toolbar advertises `y copies`, as the design does, but `y` is step 9.

## Open defects

- None for this step.
- `ros_tui Hybrid Keys(6).html` is still untracked in the repo root. Don't commit it.
