# Using ros_tui

```bash
ros2 run ros_tui ros_tui
```

ros_tui opens on the **☰ list**: every topic, service, action and node in the
live ROS graph, checked once a second. `enter` opens the entry under the
cursor in a tab of its own, and `/` finds anything by name or type. Keys don't
depend on focus: what a key does depends only on the layer you're on, and the
footer always says where you are and what `esc` and `enter` will do. `?` lists
every key that works right now.

## The layers

The screen is a stack of layers. **`esc` always goes up one layer and `enter`
always goes down one.**

1. **The tab row**: the ☰ list (tab 0) and the open entries (1…9). `h` `l`
   (or ← →, tab) move along it, `enter` goes into the tab.
2. **Inside a tab**: on the ☰ list, `j` `k` (↑ ↓) pick an entry and tab filters
   by kind (topics, services, actions, nodes); `enter` opens it. In an entry,
   `h` `j` `k` `l` pick an **area** (a panel such as REQUEST or RESPONSE) and
   `enter` goes into it.
3. **Inside an area**: `j` `k` pick a row (a field, a parameter, an
   interface); `enter` does the row's thing: edit it, fold or unfold it, or
   open an interface in its own tab.
4. **Insert**: typing a value. `enter` or `esc` keeps it; `tab` keeps it and
   edits the next field. A value that doesn't fit the field stays in insert
   with an error line under the panel (`esc` drops it instead).

From anywhere outside insert: `0`…`9` go to a tab, `H` `L` to the previous or
next one, `x` closes the tab, `u` undoes, `/` searches, `:` opens the command
line and `?` shows the keys. `:q`, `ctrl+q` or `ctrl+c` quit.

## Only space sends

Nothing reaches the robot by accident. **Space** (or `^s`) is an entry's one
sending key: publish once, call, send the goal, set the changed parameters, or
start and stop an echo. In insert, `^s` keeps the value and sends it. The only
other key that sends is `r`, which starts repeating a publish; `s` only ever
stops a repeat or cancels a goal. Moving and editing keys never send. A send
flashes its button and adds a line to the activity strip above the footer;
`:log` shows all of them, and `enter` there jumps to that entry's tab.

## Topics

A topic opens in **Echo** when someone publishes it and in **Publish** when
nobody does. `e` (or `:echo`, `:pub`) switches; the message you were writing
stays.

**Echo**

- Space starts the echo and stops it again. LATEST MESSAGE shows the newest
  message, one row per field, with the count, the rate and the dropped
  messages next to the button.
- `enter` goes into LATEST MESSAGE and **freezes** it, so you can read it
  while `+N new since` counts what arrives; `esc` goes live again. Inside,
  `enter` on a field hides or shows it.
- Echo picks a QoS that can hear every current publisher (best-effort if any
  publisher is best-effort). The QoS is fixed when the echo starts, so if a
  publisher with a different QoS appears later, restart the echo.
- Long arrays and strings are shortened and floats are shown to 6 significant
  digits; `y` copies the message exactly as it arrived.

**Publish**

- Space publishes the message once.
- `r` repeats it at the rate in the Repeat button (the rate the echo measured,
  your own, or 10 Hz) until `s` stops it. `R` (or `:rate 5`) changes the rate,
  0.1 to 100 Hz; a repeat that's running restarts at the new rate.
- `[` and `]` step through what you sent before.

An echo or a repeat keeps running when you switch or close its tab: the top
bar and the ☰ list show it (`◉` echoing, `↻` repeating) until you stop it.
Quitting stops everything.

## Services

Edit the REQUEST and press space. RESPONSE shows `calling…`, then `✓ OK` with
the round-trip time and the response, or `✗ FAILED` and why. If no server
appears within 5 s, or no response comes back within 30 s, the call fails.
`[` `]` step through earlier requests.

## Actions

Edit the GOAL and press space. RESULT goes EXECUTING (with the newest
feedback) and then SUCCEEDED, ABORTED, CANCELED or REJECTED, with the time it
took and the result. `s` cancels the goal. One goal runs at a time; a goal
keeps running when you close its tab, and **every running goal is canceled
when you quit**.

## Nodes

A node shows two areas:

- **INTERFACES**: what it publishes, subscribes to, serves and calls, like
  `ros2 node info`. `enter` on one opens it in its own tab.
- **PARAMETERS**: every parameter with its type and value. `enter` (or `i`)
  edits one, `c` clears it first. A change shows as `5.0 was 10.0` until space
  sets every changed parameter on the node; one the node rejects stays changed,
  with its reason in the activity strip. `u` undoes a change.

## Editing a message

A request, a goal or a message to publish is edited as **field rows**, one per
field, prefilled with the message's defaults:

- `j` `k` move, `enter` (or `i`) edits a value, `c` clears it and edits, and
  `tab` in insert moves on to the next field.
- A nested message is folded (`▸ pose {…}`) or unfolded (`▾ pose`): `enter`
  toggles it, `h` folds or goes up to the parent, `l` unfolds. Small messages
  like a Point, a Quaternion or a Header are one row, typed as
  `{x: 1.0, y: 2.0, z: 0.0}`.
- On a list, `o` adds an element and `d` deletes one. A list of numbers can
  also be typed whole: `[1, 2.5]`.
- `header: auto` sends a Header stamped at send time, and `stamp: now` fills a
  `builtin_interfaces/Time` with the current time. When repeating, both are
  filled in again for every message. `.nan`, `.inf` and `-.inf` work for
  floats.
- Everything is checked before it's sent: types, integer and float ranges,
  fixed array sizes and bounded list lengths. An error names the field, e.g.
  `a needs a whole number, got "abc"`, and nothing is sent. (The stock ROS CLI
  silently sends `UInt8(data=300)` as a different number.)
- `y` copies the message and `p` pastes it into another entry of the same type
  (a topic's message, a service's request or an action's goal). `u` undoes
  edits, pastes and helpers, one tab at a time.
- Message types are loaded the first time you open something that uses them,
  so ros_tui starts quickly even with thousands of interfaces installed.

### Field helpers

A field with a helper shows `[f …]` after its value. `f` opens a small form
under the row; `tab` picks how to enter the value, `enter` applies it (`u`
undoes) and `esc` closes it without changing anything.

| Field                      | Helper                                                              |
| -------------------------- | ------------------------------------------------------------------- |
| `std_msgs/Header`          | auto, now (with a `frame_id`), or a manual stamp and `frame_id`     |
| `builtin_interfaces/Time`  | now, seconds, or seconds and nanoseconds                            |
| `geometry_msgs/Quaternion` | x y z w (normalised), roll pitch yaw, yaw only, or axis and angle (degrees) |
| an integer with constants  | pick one of the message's constants (e.g. `level`: OK, WARN, ERROR, STALE) |

An enum field can also be typed by name: `err` is ERROR.

## Commands

`:` opens the command line; `tab` completes and `↑` `↓` pick a suggestion.

| Command              | Does                               |
| -------------------- | ---------------------------------- |
| `:log`               | show all activity                  |
| `:topics` `:services` `:actions` `:nodes` `:all` | filter the ☰ list by kind |
| `:rate 5`            | set a topic's repeat rate          |
| `:echo` `:pub`       | switch a topic to Echo or Publish  |
| `:close`             | close this tab                     |
| `:help`              | show the keys                      |
| `:q`                 | quit                               |

## Every key

These tables are the keymap in
[`ros_tui/ui/keymap.py`](../ros_tui/ui/keymap.py), which also drives the footer
and `?` (`test/test_keymap.py` checks that they match). "Also" is the familiar
alternative to a vim key; "Where" is when the key applies.

### Normal

| Key | Does | Also | Where |
| --- | ---- | ---- | ----- |
| `enter` | down one layer / do it |  |  |
| `esc` | up one layer |  |  |
| `h l` | previous / next tab | `← → tab` | tab row |
| `j k` | pick an entry | `↑ ↓` | ☰ list |
| `gg G` | top / bottom |  | ☰ list |
| `tab` | filter by kind |  | ☰ list |
| `h j k l` | pick an area | `arrows tab` | an entry |
| `i` | edit the field under the cursor | `enter enter` | an entry, editable area |
| `c` | clear it and edit |  | an entry, editable area |
| `j k` | pick a field or row | `↑ ↓` | inside an area |
| `gg G` | first / last |  | inside an area |
| `h l` | fold / unfold (h on a field: up to its parent) | `← →` | inside an area, field rows |
| `i  enter` | edit the value |  | inside an area |
| `c` | clear it and edit |  | inside an area |
| `enter` | unfold / fold a nested message or list |  | inside an area, field rows |
| `o` | add a list element after this one |  | inside an area, field rows, editable area |
| `d` | delete this list element (u undoes) |  | inside an area, field rows, editable area |
| `enter` | open it in a tab |  | inside a node's INTERFACES |
| `enter` | show / hide the field |  | inside a topic's LATEST MESSAGE |
| `f` | fill it with the matching helper |  | inside an area, a field with a helper |
| `/` | search everything | `^f` |  |
| `:log` | all activity |  |  |
| `:` | command line |  |  |
| `0 1…9` | ☰ list / tab N |  |  |
| `H L` | previous / next tab | `gT gt` |  |
| `x` | close the tab |  |  |
| `u` | undo in this tab (or reopen a closed tab) |  |  |
| `space` | start / stop echo | `^s` | an entry, topic, Echo |
| `space` | publish once | `^s` | an entry, topic, Publish |
| `space` | call | `^s` | an entry, service |
| `space` | send goal | `^s` | an entry, action |
| `space` | set changed parameters | `^s` | an entry, node |
| `r` | repeat at N Hz |  | an entry, topic, Publish |
| `R` | change the repeat rate | `:rate 5` | an entry, topic, Publish |
| `s` | stop repeating |  | an entry, topic, Publish |
| `e` | echo ⇄ publish |  | an entry, topic |
| `enter` | into the latest message: values freeze |  | topic, Echo |
| `esc` | out again: values go live |  | inside an area, topic, Echo |
| `s` | cancel goal |  | an entry, action |
| `y  p` | copy / paste a message |  | an entry, not a node |
| `[ ]` | older / newer sends |  | an entry, not a node, not Echo |
| `u` | undo a parameter change |  | an entry, node |
| `?` | all keys right now |  |  |

### After `g`

| Key | Does | Also | Where |
| --- | ---- | ---- | ----- |
| `gg` | to the top |  |  |
| `gt` | next tab |  |  |
| `gT` | previous tab |  |  |

### Insert (typing a value)

| Key | Does | Also | Where |
| --- | ---- | ---- | ----- |
| `type` | a rate in Hz (0.1–100) |  | typing a rate |
| `enter / esc` | keep it (u undoes later) |  | typing a rate |
| `^s` | keep it and publish once |  | typing a rate |
| `type` | change the value |  |  |
| `esc / enter` | keep it, back to normal |  |  |
| `tab` | keep it, edit the next field |  | typing a field |
| `^s` | keep it and set it |  | typing a parameter |
| `^s` | keep it and send |  |  |

### Search (`/`)

| Key | Does | Also | Where |
| --- | ---- | ---- | ----- |
| `type` | find by name or type |  |  |
| `↑ ↓` | pick | `^n ^p` |  |
| `enter` | open in a tab |  |  |
| `esc` | close |  |  |

### Command line (`:`)

| Key | Does | Also | Where |
| --- | ---- | ---- | ----- |
| `type` | a command, e.g. rate 5 |  |  |
| `tab` | complete |  |  |
| `enter` | run |  |  |
| `esc` | cancel |  |  |

### Activity log (`:log`)

| Key | Does | Also | Where |
| --- | ---- | ---- | ----- |
| `j k` | move | `↑ ↓` |  |
| `gg G` | newest / oldest |  |  |
| `enter` | go to that entry's tab |  |  |
| `esc` | close |  |  |

### Field helper (`f`)

| Key | Does | Also | Where |
| --- | ---- | ---- | ----- |
| `j k ↑ ↓` | next option / way to enter it |  | Enum |
| `tab` | next option / way to enter it |  | other helpers |
| `0–9` | jump / next field |  | Enum |
| `↑ ↓` | jump / next field |  | other helpers |
| `type` | change the value |  | other helpers |
| `enter` | apply (u undoes) |  |  |
| `esc` | cancel, nothing changes |  |  |

## Noisy RMW output

Some RMW implementations print warnings straight to the terminal, over the
UI. Send stderr to a file to keep the screen clean:

```bash
ros2 run ros_tui ros_tui 2>>/tmp/ros_tui.stderr
```
