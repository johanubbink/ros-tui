# Design principles and style guide

This is the guide for anyone changing the ros_tui UI. It covers why the UI is
the way it is, the rules that keep it predictable, and how it looks and talks.
The source of truth for the target UI is the "Hybrid Keys" prototype,
[`docs/design/hybrid-keys.html`](design/hybrid-keys.html). Open it in a browser
and use the keyboard.

It is a living document. It was started in Phase 0 of the redesign, while the
old four-tab UI was still in place. Each step's verification agent checks the
step against this page and adds what the step introduced (see
[agentic-dev.md](agentic-dev.md)). Sections marked **(target)** describe code
that doesn't exist yet. Treat them as the spec until they're built, then drop
the mark.

## Why

The UI is for someone poking at a live robot from a terminal, often over SSH,
often in a split pane. Three goals follow from that, and every rule below
serves one of them.

1. **Width is precious.**
   - There is no sidebar or permanent list pane; the default terminal is 124×34.
   - The list of everything is a tab of its own (☰, tab 0), and an opened entry
     gets the full width.
   - Help, search and commands are overlays that appear when asked for and then
     go away.
2. **Behaviour is predictable on every layer.**
   - The UI is a strict stack of layers. **esc always goes up one layer and
     enter always goes down one.**
   - What a key does depends only on the layer and the entry, never on where
     keyboard focus happens to be.
   - The footer always says which layer you're on and what esc and enter will
     do.
3. **Nothing reaches the robot by accident.**
   - What's in the editor goes out on space or `^s`, and on nothing else. The
     only other key that sends is `r`, which starts a repeating publish; `s`
     only ever stops or cancels. See keymap rule 3.
   - Navigation and editing keys (enter, esc, tab, the arrows, hjkl, typing)
     never send anything. A send flashes when it goes out and lands in the
     activity strip.
   - Values are validated before anything is sent. An invalid value is never
     sent, and the error names the field.

## The layer model

| # | Layer | What it is | Move | esc | enter |
|---|-------|-----------|------|-----|-------|
| 1 | **Tab row** (`tabs`) | the row of open tabs (☰ list, 1…9) | `h` `l`, ← →, tab / shift+tab | nothing ("top layer — :q quits") | go into the tab under the cursor |
| 2 | **Inside a tab** (`in`) | on ☰: the mixed list; on an entry: its areas (panels) | ☰: `j` `k`, ↑ ↓, tab cycles the kind chips. Entry: `h` `j` `k` `l`, arrows, tab pick an area | up to the tab row | ☰: open the entry under the cursor. Entry: into the picked area |
| 3 | **Inside an area** (`area`) | the rows of one panel: message fields, parameters, interfaces, echoed fields | `j` `k`, ↑ ↓, tab; `gg` `G` | up to the area pick ("back out", or "go live" on a frozen echo) | do the row's thing: edit a field or parameter, open an interface in a tab, show or hide an echoed field |
| 4 | **Insert** (`edit`) | typing into one value | typing; tab keeps it and edits the next field | keep it (if it's invalid: drop it and keep the old value, with a toast) | keep it (if it's invalid: stay, with an errline) |

`i` and `a` edit the field under the cursor, `c` clears it and edits. From the
area pick they go straight to Insert.

**Overlays** sit on top of the layers and don't change them. Closing an overlay
returns to exactly the layer and cursor you were on.

| Overlay | Opens with | Mode badge | Closes with |
|---------|-----------|------------|-------------|
| Search | `/` or `^f` | SEARCH | esc (stay where you were), enter (open the match in a tab) |
| Command line | `:` | COMMAND | esc or backspace on empty (cancel), enter (run) |
| Which-key | `?` (all keys); the `g` prefix shows its own small popup | (unchanged) | any key |
| Field helper | `f` on a field with a helper | HELPER | esc (cancel, nothing changes), enter (apply; `u` undoes) |
| Activity log | `:log` | (unchanged) | esc (close), enter (go to that entry's tab) |

When several are open, keys go to the topmost first: which-key, then the
helper, the command line, the log, search, insert, and finally normal mode.

**Global keys in normal mode** work on layers 1–3: `0`–`9`, `H` `L` (also `gT`
`gt`), `x`, `u`, `y`, `p`, `/`, `:`, `?`, `g…`.

**Entry verbs** work on layers 2–3 of an entry: space, `^s`, `s`, `r`, `R`, `e`,
`f`, `[` `]`.

## Keymap rules

Follow these when adding or changing a key.

1. **Pick its layer or context first.**
   - A key belongs to a layer (tabs, in, area, edit), an overlay, or an entry
     kind (and mode, e.g. topic Publish).
   - It does nothing anywhere else. A key with no meaning in a context logs
     `nothing on "z" here — ? shows the keys`; it never falls through to a
     different action.
2. **Pair a vim key with a familiar one** where that makes sense:
   - `j` `k` with ↑ ↓, and `h` `l` with ← →
   - `/` with `^f`, `H` `L` with `gT` `gt`, and space with `^s`
   - enter, esc and tab always work, so nobody has to know vim.
3. **Space and `^s` send; `r` repeats; nothing else sends.** This follows
   the prototype's "Keys right now" list (`keyList()` in the design), minus
   its `.` (resend the last send), which was dropped.
   - Space, with `^s` as its alias, is the entry's primary verb: publish once,
     call, send the goal, set the changed parameters, or start / stop an echo.
     In Insert, `^s` keeps the value and sends; a value that doesn't validate
     is never sent.
   - `r` (topic Publish only) starts repeating the publish at the shown rate,
     with `↻`, until `s` stops it. `R` (or `:rate 5`) changes the rate.
   - `s` only ever stops: it stops a repeat or cancels a goal.
   - No other key sends, and no navigation or editing key ever does. A send
     always flashes its button and adds an activity line.
   - In `keymap.py`, `primary` is dispatched by space and `^s` only, and the
     "Do (only these send)" group holds nothing but space (`test_keymap.py`
     checks both).
4. **Every key is in `keymap.py` with a label.**
   - `KEYMAP` is a tuple of `Binding(mode, group, show, label, alias, when,
     shown, run)`. `mode` is the input mode (normal, `g`, insert, search,
     command, activity, helper, which-key), `when` lists context predicates
     (`PREDICATES`, `!` negates), `run` maps keys to `NavState` actions.
   - Dispatch takes the first row that matches; two rows that both match must
     agree. Rows with an empty `show` only dispatch, rows without `run` are only
     listed.
   - The footer, the `?` which-key (`keys_now`), the `g…` popup
     (`which_key_items`) and the tutorial (`scripts/export_keymap.py`, JSON)
     are all generated from it.
   - A key that isn't in the table doesn't exist. Its label is the short phrase
     the prototype uses, e.g. "pick an area", "into the latest message: values
     freeze".
5. **Reserved keys.** These mean the same thing everywhere they apply. Don't
   reuse them for something else:
   - Layers: `esc` `enter`
   - Sending: `space` `^s` `r` `s` (`.` is free: nothing resends)
   - Moving: `h` `j` `k` `l` and the arrows, `tab` `shift+tab`, `gg` `G`
   - Tabs: `0`–`9` `H` `L` `gt` `gT` `x`
   - Editing: `u` `y` `p` `i` `a` `c` `f` `e` `R` `[` `]`
   - Overlays: `/` `^f` `:` `?` `g`
   - Quitting: `:q`
6. **Undo is per tab.** `u` undoes only changes made in the current tab: edits,
   pastes, rate changes, parameter changes and applied helpers. The one
   exception is reopening a closed tab. If there is nothing to undo here, say
   so, and mention changes in other tabs that are being kept.

## Visual language

### Colour tokens

These are from the design's `:root`. They live in one place,
`ros_tui/ui/theme.py`: `TOKENS` (these plus the greys and surfaces of the
design's terminal CSS), `KINDS` (the kind table below) and `MODES` (the footer
badges). Rich text in widgets names a token (`style('key', 'tab-cur')`); textual
CSS uses the same values as `$rt-<token>`, `$rt-kind-<kind>` and
`$rt-mode-<mode>` (`theme.css_variables()`, merged in by the app). Don't put hex
values in widget code or CSS; add a token instead.

| Token | Value | Use |
|-------|-------|-----|
| `term` / `term-2` / `term-3` | `#121212` / `#181818` / `#1e1e1e` | terminal background / panel body / panel title |
| `tline` | `#333333` | panel border at rest |
| `text` | `#c9d1d9` (terminal text `#dcdcdc`) | body text |
| `muted` / `faint` | `#7d8794` / `#4d5662` | secondary text / hints, dim lines |
| `accent` | `#3a96dd` | entry names in headers |
| `accent-fill` | `#0178d4` | primary buttons, the inside-an-area panel border |
| `key` | `#eceff4` | key caps in hints, the selected-panel border, the tab-row cursor |
| `ok` | `#89d185` | success, "● live", ↻ repeating, INSERT badge |
| `live` | `#4fd8e8` | running: ◉ echoing, the action spinner, "calling…" |
| `warn` | `#ffd08a` | ❄ FROZEN, "+N new since", canceled, "● changed", stop buttons |
| `bad` | `#f48771` | errors: errlines, bad toasts, ✗ |

Syntax colours in message rows: field keys `#9cdcfe`, numbers `#b5cea8`,
strings `#ce9178`, type hints `#5c6f5c`.

### Entry kinds

Every entry carries its kind's glyph in its kind's tint: in the list, in tabs,
in search results, in activity lines and in the entry header (`≋ TOPIC`).

| Kind | Glyph | Colour | Tag background |
|------|-------|--------|----------------|
| topic | `≋` | `#5fb3a8` | `#14302c` |
| service | `⇄` | `#a597ea` | `#241f3d` |
| action | `▷` | `#d995b9` | `#3a1f2f` |
| node | `◆` | `#93a4b8` | `#222a33` |

The active tab is underlined in its kind's colour, and the ☰ tab in
`accent-fill`.

### Panels: selected vs. inside

An entry's body is made of panels (areas): MESSAGE, LATEST MESSAGE, REQUEST and
RESPONSE, GOAL and RESULT, INTERFACES and PARAMETERS. The title is in capitals
and carries hints on the right.

- **At rest**: a `tline` border.
- **Selected** (layer 2, the area under the cursor): a `key` (near-white)
  border, title on `#262b33`.
- **Inside** (layers 3 and 4): an `accent-fill` (blue) border, title on
  `#16283a`. The current row gets a `#22303e` background with a 2-cell blue bar
  on its left.

On the ☰ list the same logic applies to rows: the cursor row is `#2b3a4a`, with
a `key` outline while the list has the keys.

### Terminal approximations

The design is HTML; the terminal has whole cells and no borders between them.
These are the agreed stand-ins. Use them, rather than inventing new ones:

- **Tab underline**: the tab row is two lines. Under the tabs is a rule of `▔`
  in `rule`; the active tab's stretch of it is in its kind's tint (`accent-fill`
  for ☰). This stands in for the design's 2px `border-bottom`.
- **Tab-row cursor**: the cursor tab gets `▏` `▕` edges in `key`, `key` text and
  the `tab-cur` background, for the design's 1px outline.
- **List cursor**: the cursor row has the `cursor` background; while the list has
  the keys (layer `in`) it turns `cursor-on` and gets a `▍` bar in `key` in the
  first cell, for the design's `key` outline.
- **Chips and switches** (kind chips, the Echo / Publish switch): pills become
  ` label ` blocks on `term-3`, the one that is on in `bright` bold on `cursor`.
  There are no rounded borders.
- **Panels**: rounded box-drawing borders (`╭─╮│╰─╯`) in the panel's state colour
  (`tline`, `key` selected, `accent-fill` inside), a one-line title bar on the
  state's title background, then the body on `term-2`. Side-by-side panels share
  the width by the design's flex weights (`PANEL_WEIGHTS`).
- **Overflow markers**: `‹ N more` and `N more ›` in `key` at the edge of the tab
  row that hides tabs. The row scrolls by whole tabs.
- The design's 1px rules above the activity strip and the footer are left out:
  a whole row each is too much at 34 lines. The strip and the footer keep their
  own backgrounds (`strip`, `foot`) instead.

### Footer contract

The footer is one line, and it always shows, from left to right:

1. **Mode badge**:
   - NORMAL `#6a8fb3`
   - INSERT `ok` green
   - HELPER `#e6c07b`
   - SEARCH `#c9d1d9`
   - COMMAND `#c586c0`

   The badge is dark text (`#121212`) on the colour.
2. A pending prefix, e.g. `g…`.
3. **Breadcrumb**: `tabs › /chatter › latest message › editing`. The last part
   is bold white, the rest dim.
4. Pushed right: **`esc <what it does here>`** and **`enter <what it does
   here>`**, e.g. `esc go live`, `enter show / hide field`, `enter open
   /chatter`. Either one is left out when it does nothing.
5. `f <Helper> helper` when the row under the cursor has one, then `? keys`.

The command line replaces the footer while it's open: COMMAND, the typed
`:text`, then "↑↓ pick · tab completes · enter runs · esc cancels".

### State markers

- **Running**:
  - `◉` (`live`) is a topic being echoed and `↻` (`ok`) a topic repeating.
  - The `◐◓◑◒` spinner (`live`) is an action executing.
  - Markers show in the tab, in the top bar's running list, and in the list's
    Here column (`◉ echoing`, `↻ 10 Hz`, `◐ running`, `open`).
- **Echo live vs. frozen**:
  - The LATEST MESSAGE title says `● live · enter freezes it`.
  - Going inside freezes the values: a `❄ FROZEN` pill, then `+N new since`
    (`warn`), then `esc goes live`.
  - Leaving the area makes it live again. With nobody publishing, it says
    `waiting — nobody publishes this yet`.
- **Pills** in panel titles:
  - `calling…` (running, `live` on `#0f3a40`)
  - `✓ OK` / `SUCCEEDED` (`ok` on `#173a17`)
  - `CANCELED` (`warn` on `#3a3010`)
  - each followed by the timing, e.g. `4.0 ms` or `3.5 s · live feedback`.
- **Buttons** carry their key:
  - `▶ Publish once space` is primary (`accent-fill`).
  - `■ Stop echo space` is the stop style (orange on `#4a2a12`).
  - Disabled buttons are dim and say why next to them ("a goal is running on
    /fibonacci").
- **Flash**: a send outlines its button white for 0.5 s.
- **Toasts** sit bottom-right in the body, for about 1.6 s, with one short line:
  - ok: green on `#173a17`
  - info: `#8fc3ec` on `#16283a`, e.g. "closed /chatter · u undoes"
  - bad: `bad` on `#3a1515`, e.g. "nothing copied yet (y copies)"
- **Errlines** go at the bottom of the panel they're about: `✗` and the
  message in `bad` on `#201414`. They name the field. They clear when the value
  is fixed, or after about 6 s.
- **Activity strip**:
  - It sits above the footer, headed "ACTIVITY · ALL TABS", and shows the three
    newest lines (time, kind glyph and entry, text).
  - Lines from other tabs are dimmed. A new line is highlighted (green bar, or
    red for a failure) for about 1.6 s.
  - `:log` shows them all.
- **Helper badges**: a field with a helper shows `[f Quaternion]`,
  `[f Header]` or `[f Enum]` at the end of its row. When the cursor is on such a
  row, the panel title and the footer say `f opens the Quaternion helper`.

## Copy and tone

Short, plain and lowercase, with no full stop. Say what happened, then what to
do next. Join the two with " — ", separate hints with " · ", and quote the
user's bad value. Examples from the prototype to copy the style from:

| Situation | Text |
|-----------|------|
| undo with nothing here | `nothing to undo in this tab (1 change in another tab is kept)` |
| helper can't apply | `fix the highlighted values first` |
| closed a tab | `closed /chatter · u undoes` |
| wrong type in the register | `copied a String, this needs a PoseStamped` |
| field error (name the field) | `level needs OK / WARN / ERROR / STALE or a number, got "hot"` |
| range error | `rate must be 0.1–100 Hz, got "500"` |
| esc on an invalid value | `rate must be 0.1–100 Hz, got "500" — kept the old value` |
| blocked send | `a goal is already running on /fibonacci — s cancels it` |
| nothing to act on | `start the echo first (space)`, `change a value first (enter edits it)` |
| no helper | `no helper for this field — fields with one show [f …]` |
| unknown command | `unknown command :foo — : then tab lists them` |
| unknown key | `nothing on "z" here — ? shows the keys` |
| an empty state | `nothing yet — what you send shows up here`, `waiting — nobody publishes this yet` |
| a successful action | `✓ response · sum: 42 (4.0 ms)`, `↻ repeating at 10 Hz`, `■ goal canceled after 2.5 s` |

- Activity lines start with a glyph: `✓` for done, `▶` for sent or called,
  `↻` for repeating, `■` for stopped or canceled, `✗` for failed.
- Mention the undo when there is one: "(u undoes)".
- Use the field's path as the user sees it (`pose.orientation`, `points[1].x`),
  never an internal name.

## Code principles

- **A pure model with thin widgets.**
  - `ros_tui/ui/nav.py` and `ros_tui/ui/keymap.py` are plain Python: no
    textual, no rclpy (`test_keymap.py` checks). So is `ros_tui/ui/fields.py`,
    the row model of a message **(target)**. They are unit-tested on their own
    (`test/test_nav.py`, `test/test_keymap.py`, over the design's world in
    `test/harness/nav_world.py`).
  - `NavState` holds the catalogue (the ☰ list, fed by `set_catalog` from a
    `GraphSnapshot`), the open tabs, the active tab, the layer, the tab, list,
    area and row cursors, the kind chip, the overlays, the `g` prefix, the undo
    stack, the key log and the toast. `footer()` gives the mode, breadcrumb,
    esc / enter labels, pending prefix and helper hint; `summary()` is the same
    as plain data for the harness.
  - What an entry holds comes from an `EntryProvider`: its areas (`AREAS`, by
    screen), its row count, `start_edit` / `commit_edit` (returning a `Commit`:
    kept with a log line and an optional `UndoEntry`, or an error), `activate_row`,
    the esc label and log line for leaving an area, the helper of a row, label
    values like the rate, `verb` (primary, secondary, repeat, rate, history,
    yank, paste, helper) and `undo`. The default has the design's areas, no
    rows and a topic's Echo / Publish mode (`e`); other verbs log "not built
    yet". Entry kinds subclass it.
  - `handle_key` asks `keymap.lookup` for an action name and runs it from
    `nav.ACTIONS`, a flat table of one-line calls into `NavState` methods. Keys
    an overlay or insert doesn't use are swallowed; an unused typing key in
    normal mode logs a hint ("nothing on "z" here").
  - Undo entries carry an owner: the tab key they were made in, or `*` for a
    closed tab, the one entry any tab can undo.
  - Widgets render the model and pass on keys; they make no decisions.
    Every view of the new UI is a `NavView` (`ros_tui/ui/widgets/base.py`): it
    holds the `NavState`, never takes focus, has no bindings, and implements
    `lines(width, height)`, returning one Rich `Text` per screen row, which
    `render()` crops to the width. After each key and each graph update the app
    calls `refresh_views()`, which re-renders all of them. Shared text helpers
    (`style`, `fit`, `spread`, `glyph`, `keyed`) live in `base.py`; a widget may
    keep only view state that the model doesn't need, such as a scroll offset
    (the tab row's first tab, the list's top row).
  - Everything the footer, the tests and the tutorial need to know comes from
    the model. The harness reads it through `app.harness_state()`.
- **One key router.**
  - The app (`ros_tui/ui/next_app.py`, `ros_tui --next` until step 10) has one
    `on_key` that hands every key to `NavState.handle_key`, which looks it up in
    `keymap.py`. The app and its screen don't inherit textual's bindings (tab
    focus cycling, the ctrl+p palette), so tab, shift+tab and ctrl+p reach the
    keymap too; only ctrl+q and ctrl+c are bound, to quit. It takes textual
    key names (`slash`, `question_mark`, `shift+tab`, `ctrl+s`) or characters;
    `normalize_key` makes them one canonical name. There are no per-widget
    bindings and no focus-dependent behaviour.
  - Per-layer predictability is the point of the design. Focus-driven bindings
    are what made the old UI hard to reason about.
- **The keymap is the single source of truth.** Dispatch, the footer labels,
  `?`, the `g…` popup and `scripts/export_keymap.py` (the tutorial) all read the
  same table.
- **State is per entry and per tab.** Edits, undo, send history, area and row
  cursors and the echo's shown/hidden fields belong to the entry they were made
  in. Switching tabs never loses them.
- **The bridge is the only rclpy boundary.**
  - The UI only calls `RosBridge` methods. Results come back as textual
    messages (`ros_tui/ui/messages.py`) or Futures.
  - The ROS layer (`ros_tui/ros/`) never imports textual.
  - In tests, `FakeBridge` (`test/harness/fake_bridge.py`) stands in for it, and
    has to keep up with any new bridge method.
- **Validation lives in one place.** `build_message` (`message_yaml.py`) checks
  types, ranges and sizes. It reports each problem as a `FieldError` with the
  field path, and the UI maps that path to a row and an errline. Don't add a
  second validator in a widget.
- **Every tunable number lives in `ros_tui/constants.py`.**
- **Time on screen comes from an injectable clock** **(target)**. Rates, call
  timings and elapsed times read the bridge's clock rather than
  `time.monotonic()`, so `FakeBridge`'s `ManualClock` makes every shot
  repeatable. The old UI still reads the real clock (the echo Hz and "response
  in … ms").
- **Every step ships a scenario test with shots** (`test/ui/test_stepNN_*.py`).
  See [agentic-dev.md](agentic-dev.md).

### Checklist: adding an entry kind (target)

- [ ] Add a glyph and tint to the kind table (and to this page). The glyph must
      not clash with the existing ones, and the tint must be readable on
      `term`.
- [ ] Add `ros_tui/ui/entries/<kind>.py`. It declares its areas (titles in
      capitals) and its verbs: primary (space / `^s`), secondary (`s`), repeat
      (`r` / `R`), history (`[ ]`), and yank / paste with the register type,
      as an `EntryProvider` subclass.
- [ ] Give every verb a row in `keymap.py`, in the kind's context, with a
      label.
- [ ] Give each area an enter label and an esc label for the footer.
- [ ] Add the bridge calls to `RosBridge` and `FakeBridge`, live behaviour
      included. Add the kind to `DEMO_GRAPH`, the demo servers and the design.
- [ ] Show its running marker in the tab, the top bar and the Here column, if
      it has one.
- [ ] Write a scenario test with shots, and add design references to
      `docs/design/reference_shots.json`.

### Checklist: adding a field helper (target)

- [ ] Write the maths or parsing as pure functions, reusing `wizards/`
      (quaternion, header, time) where possible. Unit-test them.
- [ ] Register the helper for its type, so the row shows `[f <Name>]` and the
      footer and panel title advertise `f`.
- [ ] Follow the popup rules: a mode strip, tab for the next mode, ↑↓ between
      fields, typing changes the value, a live preview line (`= …`, or `= fix
      the values first` in `bad`), enter applies, esc cancels and changes
      nothing.
- [ ] An applied helper is one undo step.
- [ ] Write a scenario test with shots: open, change mode, apply, and esc
      leaving the value unchanged.

### Checklist: adding a key

- [ ] Pick the layer, overlay or entry context, and check that the key isn't
      reserved for something else there.
- [ ] Add the vim key and the familiar alias, if there is one.
- [ ] If it sends, stop: only the verbs above send. Rethink the key, or make it
      an explicit verb with a flash and an activity line.
- [ ] Add it to `keymap.py` with a label and a group, which updates the footer,
      `?` and the tutorial. Its action goes in `nav.ACTIONS`.
- [ ] Add it to the design prototype too, if it's user-visible, so the reference
      shots and the tutorial stay in step.
- [ ] Add a transition test in the nav model tests, and a shot if it changes
      the screen.

## Screenshots

Screenshots of the key states are added here from the harness
(`scripts/agent_check.sh`) when the new UI switches over (step 10). Until then,
compare with the design's reference shots (`scripts/design_shots.py`, written to
`test/artifacts/design/`).
