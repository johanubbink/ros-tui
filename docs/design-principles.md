# Design principles and style guide

The guide for anyone changing the ros_tui UI: why it is the way it is, the
rules that keep it predictable, and how it looks and talks. A change that adds
a rule, a pattern or a look adds it here too. [usage.md](usage.md) is the
user's side of the same keys, [architecture.md](architecture.md) the map of the
code.

## Why

The UI is for someone poking at a live robot from a terminal, often over SSH,
often in a split pane. Every rule below serves one of three goals.

1. **Width is precious.** No sidebar: the list of everything is a tab of its
   own (☰, tab 0) and an opened entry gets the full width. Help, search and
   commands are overlays that come when asked for and go away. The default
   terminal is 124×34, and it still works at about 83 columns: when a line
   doesn't fit, the hint on its right gives way first (`spread(...,
   optional=True)`), so chips and buttons stay whole
   (`test_shell.py::test_narrow_terminal`).
2. **Behaviour is predictable on every layer.** The UI is a strict stack of
   layers: **esc always goes up one, enter always goes down one.** What a key
   does depends only on the layer and the entry, never on keyboard focus. The
   footer always says which layer you're on and what esc and enter do.
3. **Nothing reaches the robot by accident.** Only space / `^s` (the entry's
   primary verb) and `r` (start a repeating publish) send; `s` only stops or
   cancels. With the mouse, only a click on a button showing one of those keys
   does the same. Navigation, editing and typing never send. Values are
   validated before a send; an invalid value is never sent, and the error
   names the field. Every send flashes its button and adds an activity line.

## The layer model

| # | Layer | What it is | Move | esc | enter |
|---|-------|-----------|------|-----|-------|
| 1 | **Tab row** (`tabs`) | the open tabs (☰, 1…9) | `h` `l`, ← →, tab / shift+tab | nothing ("top layer — :q quits") | into the tab |
| 2 | **Inside a tab** (`in`) | ☰: the list; an entry: its areas (panels) | ☰: `j` `k`, ↑ ↓, tab cycles the kind chips. Entry: `h` `j` `k` `l`, arrows, tab | up to the tab row | ☰: open the entry. Entry: into the area |
| 3 | **Inside an area** (`area`) | the rows of one panel | `j` `k`, ↑ ↓, tab; `gg` `G`; `h` `l` fold / unfold field rows | up to the area pick ("go live" on a frozen echo), however deep the row | the row's thing: edit, fold / unfold, open an interface, show / hide an echoed field |
| 4 | **Insert** (`edit`) | typing one value | typing; tab keeps it and edits the next field | keep it (invalid: drop it, keep the old value, toast) | keep it (invalid: stay, with an errline) |

`i` and `a` edit the field under the cursor, `c` clears it and edits; from the
area pick they go straight to Insert.

**Overlays** sit on top of the layers and don't change them; closing one
returns to exactly the layer and cursor you were on. At most one is open
(`NavState.overlay`), and it has the keys.

| Overlay | Opens with | Mode badge | Closes with |
|---------|-----------|------------|-------------|
| Search | `/` or `^f` | SEARCH | esc (stay), enter (open the match) |
| Command line | `:` | COMMAND | esc or backspace on empty, enter (run) |
| Which-key | `?`; the `g` prefix shows its own popup | (unchanged) | any key |
| Field helper | `f` on a field with a helper | HELPER | esc (nothing changes), enter (apply; `u` undoes) |
| Activity log | `:log` | (unchanged) | esc, enter (go to that line's tab) |

Global keys in normal mode work on layers 1–3: `0`–`9`, `H` `L` (`gT` `gt`),
`x`, `u`, `y`, `p`, `/`, `:`, `?`, `g…`. Entry verbs work on layers 2–3:
space, `^s`, `s`, `r`, `R`, `e`, `f`, `[` `]`.

### The mouse

The keys do everything; a left click is a shortcut to what a key does, and logs
`click` where the key would log itself.

- **Targets** (`nav.CLICKS`): a tab (as `0`–`9`), its `×` (as `x`), a kind chip
  (as tab on the list), a list row / search match / activity or `:log` line (as
  enter: open or go to the entry), a panel (select and go inside), a half of the
  Echo / Publish switch (as `e`), a button (its key), the rate in the Repeat
  button (as `R`), the top bar's search box (as `/`).
- **One way in.** A view tags what it draws with `widgets.base.clickable` (a
  Rich `meta`; `button()` and `switch()` do it for their parts). Every view
  hands clicks to `RosTuiApp.click`, which calls `NavState.click(target,
  on_popup)`. Nothing else handles the mouse.
- **Popups are modal.** While a popup has the keys, only a click on it counts; a
  click elsewhere closes it as esc does and does nothing more.
- **Typing is kept first.** A click while typing keeps the value as esc does,
  then does its thing; on the primary button it keeps it as `^s` does and sends.
- A disabled button has no target. The wheel, drags and right clicks do nothing.

## Keymap rules

1. **Pick its layer or context first.** A key belongs to a layer, an overlay,
   or an entry kind (and mode). Anywhere else it does nothing and logs
   `nothing on "z" here — ? shows the keys`; it never falls through.
2. **Pair a vim key with a familiar one**: `j` `k` / ↑ ↓, `h` `l` / ← →, `/` /
   `^f`, `H` `L` / `gT` `gt`, space / `^s`. enter, esc and tab always work.
3. **Space and `^s` send; `r` repeats; nothing else sends.**
   - Space (alias `^s`) is the primary verb: publish once, call, send the goal,
     set the changed parameters, start / stop an echo. In Insert, `^s` keeps the
     value and sends.
   - `r` (topic Publish) repeats at the shown rate until `s` stops it; on a
     running repeat it only says so (`already repeating at 10 Hz — s stops
     it`). `R` (or `:rate 5`) changes the rate.
   - `s` stops a repeat or cancels a goal, nothing else.
   - In `keymap.py`, `primary` is dispatched by space and `^s` only, and the
     "Do (only these send)" group holds only space (`test_keymap.py`).
4. **Every key is in `keymap.py` with a label.** `KEYMAP` is a tuple of
   `Binding(mode, group, show, label, alias, when, shown, run)`: `mode` is the
   input mode (normal, `g`, insert, search, command, activity, helper,
   which-key), `when` the context predicates (`PREDICATES`, `!` negates), `run`
   a tuple of `Run(keys, action, arg)` naming a `nav.ACTIONS` entry and its
   argument (a step, a verb's name). Dispatch takes the first matching row; rows
   with an empty `show` only dispatch, rows without `run` are only listed. The
   footer, `?` (`keys_now`) and the `g…` popup (`which_key_items`) are generated
   from it, and the key tables in [usage.md](usage.md) must match it
   (`test_keymap.py`). A key not in the table doesn't exist.
5. **Reserved keys** mean the same everywhere they apply:
   - layers `esc` `enter`; sending `space` `^s` `r` `s`
   - moving `h` `j` `k` `l`, arrows, `tab` `shift+tab`, `gg` `G`
   - tabs `0`–`9` `H` `L` `gt` `gT` `x`
   - editing `u` `y` `p` `i` `a` `c` `f` `e` `R` `[` `]`, and `o` `d` on field rows
   - overlays `/` `^f` `:` `?` `g`; quitting `:q`
6. **Undo is per entry.** `u` undoes your last change in this entry (edits,
   pastes, rate and parameter changes, applied helpers), or reopens the tab you
   just closed (any tab can). Switching tabs never undoes something elsewhere.
   With nothing to undo: `nothing to undo here`.

## The field-row editor

Every message the user fills in (a topic's message, a service request, an
action goal) is edited as **field rows**, one per field, expanding in place.
Model: `ui/fields.py` (`FieldRows`); view: `widgets/field_rows.py`; keys:
`entries/message.py` (`MessageEntry`).

| Shape | Looks like | enter | Typed as |
|-------|-----------|-------|----------|
| leaf | `1  a: 19    # int64` | edit | the value; a string takes bare text, quotes only to force YAML (`'42'`) |
| compact message | `3  header: auto    # Header` | edit | one flow map, `{x: 1.0, y: 2.0}`; left-out keys keep their value; `header: auto`, `stamp: now` stamp at send |
| other nested message | `▸ pose {…}` / `▾ pose` | fold / unfold | its fields, one level in |
| list or array | `▸ points [3 items]` | fold / unfold | elements `[0]`, `[1]` …; a list of numbers or strings can also be typed whole (`i`) |

- **Compact types** (`fields.COMPACT_TYPES`: Point, Point32, Vector3,
  Quaternion, Pose2D, Header, Time, Duration) are a short list on purpose: only
  values that fit one line and are usually typed in one go.
- A message whose only field is a message, or whose fields are all compact
  (Pose, Twist, Transform: `fields._compact_parents`), starts unfolded.
- **Folding** has its own keys since esc means "up": enter toggles, `h` / ←
  folds or jumps to the parent, `l` / → unfolds or steps into the first field.
  Folds are remembered per entry.
- **Lists**: `o` adds an element after the cursor (at the end on the list's
  row) and edits it; `d` deletes one. Each is one undo step. Fixed arrays and
  bounded lists refuse (`k always has 9 elements`, `holds at most 3
  elements`).
- tab / shift+tab in insert keep the value and edit the next / previous typable
  row. A `0` number or a bool starts **fresh**: the first key replaces it.
- **Validation**: a typed value is parsed by its row (`a needs a whole number,
  got "abc"`), then the whole message by `build_message`; its `FieldError` is
  shown when its path is at or inside the edited row (`status[0].level must be
  an integer in [0, 255], got 300`).
- **Before a send** the message is built again. If that fails, nothing is sent:
  the folds open to the field (`FieldRows.reveal`), the cursor goes there, the
  value turns red, the errline names it and the toast says `fix the highlighted
  values first`.
- **History**: every send goes to the front of the entry's history
  (`SEND_HISTORY_MAX`); `[` / `]` step through it, `]` past the newest brings
  back the draft. The title shows `[ ] history (n)` or `#i/n`.
- **Echoed messages** use the same rows, flattened (`fields.flat_rows`), each
  named by its path. Floats are cut for display only, to
  `ECHO_DISPLAY_DIGITS` significant digits (`fields.readable`); what the entry
  keeps, and what `y` copies, is exact.
- The type is imported in a worker (`MessageEntry.load_types`); until then the
  editor says `loading…` or `✗ could not load it: …`.

## The register (y / p)

One register for the whole app (`NavState.register`, a `register.Register`).

- **y** copies what you see: in Echo the message LATEST MESSAGE shows (the
  frozen one while frozen, else the newest), exact, not the cut display; in an
  editor what it holds. On a node: `nothing to copy on a node`.
- **It is typed**: full type plus role (`message`, `request`, `goal`). `p`
  pastes only into an editor of the same type and role; otherwise `copied a
  String, this needs a PoseStamped`. In Echo: `switch to Publish (e) to paste`.
  Empty: `nothing copied yet (y copies)`.
- **A paste** replaces the whole message, is one undo step (none if nothing
  changed) and never sends. While the register holds something the top bar
  shows `copied: String from /chatter · p pastes` in `reg`.

## Field helpers

`f` on a field row with a helper opens a popup under the row that fills the
value. Model: `ui/helpers/` (pure); view: `widgets/helper_popup.py`; opened and
applied by `MessageEntry`, so every message editor has them.

| Kind | Rows | Modes (tab / shift+tab) | Writes |
|------|------|-------------------------|--------|
| Quaternion | `geometry_msgs/Quaternion` | `x y z w`, `roll pitch yaw (°)`, `yaw only (°)`, `axis + angle (°)` | `{x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}` |
| Header | `std_msgs/Header` | `auto`, `now`, `manual` | `auto`, `{stamp: now, frame_id: map}`, … |
| Time | `builtin_interfaces/Time` | `now`, `seconds`, `sec + nanosec` | `now`, `{sec: 2, nanosec: 500000000}` |
| Enum | an integer with enum constants | a list of options | the number |

- **Keys** (keymap mode `helper`; the popup takes every key): enum `j` `k` ↑ ↓
  pick, a digit jumps; others tab for the mode, ↑ ↓ ← → for the field, typing
  replaces then edits. enter applies, esc cancels (`helper closed, nothing
  changed`).
- **Applying** writes the value as text through the row, so it is checked like
  an edit and is one undo step. While the fields make no value, enter keeps the
  popup open with `fix the highlighted values first`.
- **Enums in insert** take a constant's name or prefix, any case, or a number
  (`fields.enum_value`); the completion (`fields.enum_matches`, in `comp`)
  replaces the type hint while typing. At rest: `level: 2 ERROR`.
- A row with a helper shows a `[f Quaternion]` badge; `f` elsewhere says `no
  helper for this field — fields with one show [f …]`.

## Visual language

### Colours

All colours live in `ui/theme.py`: `TOKENS`, `KINDS` (the kind table),
`MODES` (footer badges) and `TONES` (tone → text and fill, for pills and
toasts). Rich text names a token (`style('key', 'tab-cur')`); textual CSS uses
`$rt-<token>`, `$rt-kind-<kind>`, `$rt-mode-<mode>` (`theme.css_variables()`).
Never put a hex value in widget code or CSS; add a token, with a comment saying
what uses it. The ones that carry meaning:

| Token | Use |
|-------|-----|
| `text`, `muted`, `dim` | body text; secondary (an entry's type); hints and empty states |
| `accent` / `accent-fill` | entry names / primary buttons, the inside-an-area border |
| `key` | key caps, the selected-panel border, cursors |
| `ok` | success, `● live`, `↻` repeating, INSERT |
| `live` | running: `◉` echoing, the goal spinner, `calling…` |
| `warn` | `❄ FROZEN`, `+N new since`, canceled, `● changed`, stop buttons |
| `bad` | errors: errlines, bad toasts, `✗` |
| `reg` | the register chip |

| Kind | Glyph | Tint |
|------|-------|------|
| topic | `≋` | `#5fb3a8` |
| service | `⇄` | `#a597ea` |
| action | `▷` | `#d995b9` |
| node | `◆` | `#93a4b8` |

Every entry carries its glyph in its tint: in the list, tabs, search, activity
lines and the header tag (` ≋ TOPIC `). The active tab is underlined in its
tint (☰ in `accent-fill`).

### Panels

An entry's body is panels (areas): MESSAGE, LATEST MESSAGE, REQUEST /
RESPONSE, GOAL / RESULT, INTERFACES / PARAMETERS. The title is in capitals,
then hints in `panel-hint` with keys in `key` bold, joined by " · ".

- **At rest**: a `tline` border. **Selected** (layer 2): a `key` border, title
  on `tab-cur`; in an editable area a `▍` in `row-mark` marks the row `i` would
  edit. **Inside** (layers 3–4): an `accent-fill` border, title on `panel-in`,
  the current row on a `row-in` band with a `▍` in `accent-fill`.
- A title may carry a note at its right (`Panel.aside`: `3 received · 1.0 Hz`).
- An **errline** takes the panel's last line (` ✗ ` in `bad` on `err-bg`); it
  clears when the value is kept or dropped, or after `NAV_ERRLINE_S`.
- A **changed** value not sent yet shows in `warn`, then `was <old>` in `dim`.
- **Loading**: `loading…` in `dim`, or `✗ could not load it: <error>`.
- The body scrolls to keep the current row in view; group headings are lines,
  not rows.

An entry starts with its header line (kind tag, name in `accent` bold, type in
`muted`, a topic's counts and Echo / Publish switch on the right), a blank line,
the button row (buttons left, relevant keys right), a blank line, then the
panels (`entry_body.head_lines`). A node has no button row.

### Terminal stand-ins

Whole cells and no borders between them; use these rather than inventing new
ones.

- **Tab underline**: a `▔` rule under the tabs, the active tab's stretch in its
  tint. **Tab-row cursor**: `▏` `▕` edges in `key` on `tab-cur`.
- **List cursor**: `cursor` background; `cursor-on` and a `▍` in `key` while the
  list has the keys.
- **Chips and switches** (`base.switch`): ` label ` blocks on `chip`, the one
  that is on in `bright` bold on `chip-on`, with half-cell ends (`▐` `▌`).
- **Panels**: rounded borders (`╭─╮│╰─╯`) in the state colour, a one-line title
  bar, the body on `term-2`. Side-by-side panels share the width by
  `EntryView.weights`.
- **Wrapped lines** (`wrap`, RESULT): break at a space, indent two cells,
  counting terminal cells (`cell_len`).
- **Overflow**: `‹ N more` / `N more ›` at the tab-row edges; it scrolls by
  whole tabs.
- **Overlays** are `Overlay` views (`widgets/base.py`) placed absolutely:
  `place(width, height)` returns the box, `RosTuiApp.refresh_views` applies it.
  Popups get a rounded border in their edge colour, rules of `─` in `pop-line`,
  and a picked row as a `cursor-on` band with the `▍` bar.
- **Veil** under search and `:log`: `opacity: 50%` on everything but the footer
  (the screen's `-veiled` class).
- **Edit box**: the value underlined in `bright` on `edit` (`edit-fresh` when
  the first key replaces it), then a one-cell cursor (`base.edit_value`).

### Footer

One line, left to right:

1. **Mode badge**, dark text on its colour: NORMAL, INSERT, HELPER, SEARCH,
   COMMAND (`theme.MODES`).
2. A pending prefix (`g…`).
3. **Breadcrumb**: `tabs › /chatter › latest message › editing`, the last part
   bold white.
4. Right: `esc <what it does here>` and `enter <what it does here>`, each left
   out when it does nothing.
5. `f <Helper> helper` on a row with one (not in popups or insert), then `? keys`.

The command line replaces the footer while open: COMMAND, `:text`, then its
keys.

### State markers

- **Running**: `◉` (`live`) echoing, `↻` (`ok`) repeating, the `◐◓◑◒` spinner
  (`live`, frame from the clock at `ACTION_SPINNER_HZ`) a goal executing. They
  show after the name in the tab, in the top bar's running list, in the list's
  Here column and in search rows, whether the tab is open or not. One hook
  feeds them all: `Entry.running()` returns `Running(glyph, label, tone)`;
  `NavState.running` / `running_all` read it, `widgets.base.markers` draws it.
- **Closing a tab stops its echo and repeat** (`Entry.on_close`): `closed
  /chatter — echo stopped · u reopens it`. A running goal is **not** canceled on
  close (a cancel is a send); reopening gives `s` back. **Quitting stops
  everything**: `bridge.shutdown()` cancels a running goal (waiting at most
  `SHUTDOWN_CANCEL_TIMEOUT_S`), then destroys the node.
- **Echo**: `● live · enter freezes it` or `not echoing · space starts`.
  Frozen is where the cursor is, not a flag: inside LATEST MESSAGE the values
  freeze (`❄ FROZEN`, `+N new since`), and leaving the area by any key makes
  them live again. `waiting — nobody publishes this yet` / `waiting for the
  first message…` before data. enter hides / shows a field.
- **Goals**: one runs at a time, app-wide (`LastGoal`, shared through
  `Context.single`). Space on any action tab meanwhile says `a goal is already
  running on /fibonacci` (plus ` — s cancels it` on its own tab). `s` asks the
  server to cancel; an `s` before acceptance is sent once accepted. RESULT's
  title: a pill and the time (`EXECUTING 2.4 s · live feedback`, `SUCCEEDED
  3.6 s`, `CANCELED 2.4 s · last feedback`, `ABORTED`, `REJECTED`, `FAILED`).
  Events of an ended goal change nothing.
- **Repeat rate** shows in the Repeat button, underlined, with `matches the
  publisher`, `your rate` or `default`, then `R changes it`; `N sent` follows
  while repeating. A bad rate: `rate must be 0.1–100 Hz, got "500"`. A change
  while repeating restarts it (`↻ rate now 5 Hz`).
- **Pills** (`theme.TONES`): `calling…` / `EXECUTING` in `live`; `✓ OK` /
  `SUCCEEDED` in `ok`; `CANCELED` in `warn`; `✗ FAILED`, `ABORTED`, `REJECTED`
  in `bad`; each followed by its timing.
- **Buttons** carry their key (`base.button(label, key, look)`): `pri`
  (`▶ Publish once space`), `stop` (`■ Stop echo space`), plain (`↻ Repeat at
  10 Hz r`), `off` (disabled, with the reason next to it).
- **Flash**: a send turns the primary button `bright` on `accent` for
  `NAV_FLASH_S`. The entry calls `nav.feedback.flash_send(tab)` where the send
  actually goes out, so a refused send doesn't flash; toolbars ask
  `primary_look`.
- **Toasts**: bottom-right of the body, one short line, `ok`, `info` or `bad`
  tone, for `NAV_TOAST_S`.
- **Activity strip** (`widgets/activity_strip.py`): above the footer, `ACTIVITY
  · ALL TABS`, the three newest lines (time, kind glyph and entry, text in its
  `cls` colour); other tabs' lines are dimmed while an entry is open. A new
  line is **fresh** for `NAV_ACTIVITY_FRESH_S` (`fresh-bg` band, or
  `fresh-bad-bg` for a failure). `:log` shows them all; enter or a click goes
  to that line's tab.

## Copy and tone

Short, plain, lowercase, no full stop. Say what happened, then what to do next,
joined by " — "; separate hints with " · "; quote the user's bad value; name
fields by their path as the user sees it (`pose.orientation`, `points[1].x`);
mention the undo when there is one (`u undoes`).

| Situation | Text |
|-----------|------|
| nothing to undo | `nothing to undo here` |
| closed a tab | `closed /chatter · u undoes` |
| field error | `level needs OK / WARN / ERROR / STALE or a number, got "hot"` |
| esc on an invalid value | `rate must be 0.1–100 Hz, got "500" — kept the old value` |
| blocked send | `a goal is already running on /fibonacci — s cancels it`, `still calling /add_two_ints — wait for the response` |
| a send that doesn't build | `fix the highlighted values first` (toast) and the errline |
| nothing to act on | `start the echo first (space)`, `change a value first (enter edits it)` |
| unknown command / key | `unknown command :foo — : then tab lists them`, `nothing on "z" here — ? shows the keys` |
| parameter kept, not set | `publish_rate = 5.0 (not set yet: space sets it, u undoes)` |
| empty state | `nothing yet — what you send shows up here` |
| asked to start again | `already repeating at 10 Hz — s stops it` |
| activity | `✓ response · sum: 42 (4.0 ms)`, `▶ goal sent · order: 12`, `■ goal canceled after 2.4 s`, `✗ call failed: service /add_two_ints not available (50.0 ms)`, `◉ echo started`, `✓ set publish_rate = 5.0` |

Activity lines start with a glyph: `✓` done, `▶` sent or called, `↻`
repeating, `◉` echo started, `■` stopped or canceled, `✗` failed. Their colour
comes from `cls`: `g` green, `r` red, `c` cyan, `y` yellow, `dim`.

## Code principles

- **A pure model, thin widgets.** `nav.py`, `keymap.py`, `fields.py`,
  `register.py`, `helpers/` and `entries/` are plain Python: no textual, no
  rclpy (`test_keymap.py` checks `nav`, `keymap` and `fields`). They are unit-tested on their own.
  - `NavState` (`nav.py`) holds the tabs, layer, cursors, kind chip, the one
    `overlay`, the undo stack and the register. What there is to open is its
    `Catalog` (`catalog.py`), what the UI says back its `Feedback`
    (`feedback.py`: log, toast, errlines, activity, send flash), and the `:`
    line a `CommandLine` (`command_line.py`). `footer()` and `summary()` expose
    what views and tests read.
  - `handle_key` asks `keymap.lookup` for a `Run` and calls its `nav.ACTIONS`
    entry. Overlays and insert swallow keys they don't use.
- **Entries own their kind.** `entries/base.py` is the contract: `Entry`,
  `Area` (with `editable`, `folds`, `helpers`, so the keymap asks the area, not
  its id), `Editing`, `Commit`, `UndoEntry`, `Running`, `Context`.
  `nav.entry(tab)` makes one per tab on first use (through `new_entry`,
  `kinds.entry_factory` in the app) and keeps it after the tab closes, so edits,
  history and echo survive a reopen.
  - An entry declares `AREAS` (or per mode `MODES`, a topic's Echo / Publish)
    and answers `row_count`, `start_edit` / `commit_edit`, `activate_row`, its
    labels, `running`, `tick` and `verbs()`: a table of what it offers now, by
    name. Where a verb isn't offered NavState says so itself (`NOT_HERE`).
  - An entry talks back only through `nav.feedback` (`log_line`, `show_toast`,
    `refuse`, `report_error` / `clear_error`, `add_activity`, `flash_send`) and
    NavState's `push_undo` / `drop_undo`, `begin_edit`, `set_row`. An undo step
    is an `UndoEntry(owner, revert)`: a closure that undoes it and returns the
    log line.
  - `entries/kinds.py` maps a kind to its class; every entry gets the same
    `Context` (bridge, `post`, `work`), and `Context.single(cls)` is one object
    they share.
  - An entry with a message to fill in subclasses `MessageEntry` (editor area,
    loading, editing, folding, lists, undo, history, helpers, register; every
    send starts with `_send`). `entries/service.py` is the smallest example.
- **Bridge answers on the UI thread.** An entry calls `self._bridge` and wraps
  each answer in `self._post(fn)` (the app turns it into a `UiCall` message);
  slow work that isn't a bridge call goes to `self._work(fn)`, a thread worker.
  Without them (unit tests) `fn` runs straight away. An answer changes only the
  entry and the activity lines, never the cursor or layer; edits commit to their
  row by name, so a late answer can't misplace them.
- **Widgets render, nothing more.** Every view is a `NavView`
  (`widgets/base.py`): no focus, no bindings, `lines(width, height)` returns one
  Rich `Text` per row. A view may keep only view state such as a scroll offset.
  Shared text helpers (`style`, `fit`, `band`, `spread`, `keyed`, `button`,
  `switch`, `markers`, …) live in `base.py`. Each kind's view is an
  `EntryView` in `entry_body.VIEWS`: one `Panel` per area, plus its button row,
  header note and panel weights. A popup is an `Overlay` yielded in
  `RosTuiApp.compose`.
- **One key router.** `RosTuiApp.on_key` hands every key to `handle_key`; the
  app inherits none of textual's bindings, so tab, shift+tab and ctrl+p reach
  the keymap (only ctrl+q / ctrl+c quit). `normalize_key` gives each key one
  canonical name. No per-widget bindings, no focus-dependent behaviour.
- **The keymap is the single source of truth** for dispatch, footer labels,
  `?`, the `g…` popup and docs/usage.md.
- **The bridge is the only rclpy boundary.** The UI only calls `RosBridge`;
  `ros_tui/ros/` never imports textual. `FakeBridge`
  (`test/harness/fake_bridge.py`) must keep up with every bridge method.
- **Validation lives in one place**: `build_message` (`message_yaml.py`)
  reports `FieldError`s with the path; the UI maps the path to a row. Typed
  scalars, field rows and node parameters alike, go through
  `fields.parse_scalar`.
- **Every tunable number lives in `ros_tui/constants.py`**, with the
  stamp-at-send words (`HEADER_AUTO`, `TIME_NOW`).
- **Time comes from an injectable clock.** `Feedback.clock` is the bridge's
  `now()` and `Feedback.wall` its `time_of_day()` (a `ManualClock` under
  `FakeBridge`), so every shot is repeatable; nothing in the model reads real
  time. The app's tick (`UI_TICK_PERIOD_S`) runs `NavState.tick()`, and
  redraws only when it reports a change.
- **Live data is drained, bounded.** An echo or a goal's feedback is pushed into
  an `EchoBuffer` on the ROS thread (dropping the oldest past
  `ECHO_BUFFER_MAXLEN`); the tick drains it, keeps only the newest and converts
  it for display only when shown. An idle app, or an echo in another tab, never
  redraws the body.
- **Every UI change ships a scenario test with shots** (`test/ui/test_<what>.py`,
  see [agentic-dev.md](agentic-dev.md)).

### Checklist: adding an entry kind

`entries/node.py` with `widgets/node_entry.py` is the worked example.

- [ ] A glyph and tint in `theme.KINDS` (and the table above).
- [ ] `entries/<kind>.py`: an `Entry` (or `MessageEntry`) subclass with its
      `AREAS`, `row_count`, `start_edit` / `commit_edit` (errors name the field
      and quote the value), `activate_row`, `verbs()`, and `on_open` loading
      through the bridge and `post`. Register it in `entries/kinds.py`.
- [ ] An `EntryView` in `entry_body.VIEWS`.
- [ ] Keymap rows for its verbs, with labels; enter and esc labels per area.
- [ ] Bridge calls in `RosBridge` and `FakeBridge`; the kind in `DEMO_GRAPH`
      and the demo servers.
- [ ] A running marker, if it has one.
- [ ] Unit tests (`test/test_entries_<kind>.py`) and a scenario test with shots.

### Checklist: adding a field helper

`helpers/__init__.py` with `helpers/quaternion.py` is the worked example.

- [ ] Pure maths / parsing in `helpers/<kind>.py`, tested in
      `test/test_helpers.py`.
- [ ] A name in `NAMES`; its rows by type in `BY_TYPE` or by shape in
      `helper_kind`.
- [ ] Its `MODES`, an opener (`OPENERS`) and a result (`RESULTS`) giving a
      value `fields.parse` and `build_message` accept, or None.
- [ ] No keys of its own; any new one goes in `keymap.py` under `helper`.
- [ ] A scenario test with shots: open, change mode, apply, `u`, esc.

### Checklist: adding a key

- [ ] Pick the layer, overlay or entry context; check the key isn't reserved
      there.
- [ ] Add the vim key and the familiar alias.
- [ ] If it sends, stop: only the verbs above send.
- [ ] Add it to `keymap.py` with a label and group, its action in
      `nav.ACTIONS`, and to the key tables in [usage.md](usage.md)
      (`test_keymap.py` fails until you do).
- [ ] A transition test in the model tests, and a shot if the screen changes.

## Screenshots

Key states from the scenario tests (`scripts/agent_check.sh -m shots` writes
them to `test/artifacts/`; copy one here when its look changes).

![The ☰ list](images/home.png)

A frozen echo: inside LATEST MESSAGE, `❄ FROZEN`, `+N new since`, the footer's
`esc go live`:

![A frozen echo of /chatter](images/echo-frozen.png)

A service call: REQUEST and RESPONSE, `✓ OK` with its time, the activity strip:

![/add_two_ints called](images/service-called.png)

The Quaternion helper under the row it fills:

![The Quaternion helper on /goal_pose](images/quat-helper.png)
