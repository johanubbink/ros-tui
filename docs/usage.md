# Using ros_tui

```bash
ros2 run ros_tui ros_tui
```

ros_tui has four tabs: **Topics**, **Services**, **Actions** and **Nodes**.
`ctrl+t` moves to the next one. The lists follow the live ROS graph, checked
once a second, and only redraw when something changed.

## Lists and detail views

Each tab opens on a full-width list with a filter box. Type to filter; `↑`/`↓`
move through the matches (the first one is highlighted for you) and `enter`
opens it. The list then shrinks to the left and the detail view opens on the
right: the type, the YAML editor, the buttons, and an output log at the
bottom. `ctrl+f` goes back to the list with the filter box focused.

Switching tabs keeps what you had open. Edits you make in the editor are kept
for each topic, service or action until you quit; `ctrl+r` puts the defaults
back.

## Topics

Opening a topic asks whether you want to **Publish** or **Subscribe** (`p` or
`s`, or the arrow keys and `enter`), and shows how many publishers and
subscribers it has. The **→ Subscribe** / **→ Publish** button switches later.

**Publish mode**

- **Publish** (`ctrl+s`) sends the message once.
- **Start rate** publishes it repeatedly at the rate in the box next to it
  (0.1 to 100 Hz). It keeps going while you look at other topics; the status
  line lists every topic being published. Press the button again, or `ctrl+k`,
  to stop. Everything stops when you quit.

**Subscribe mode**

- **Echo** (`ctrl+s`) subscribes and prints each message, with the message
  count, rate and dropped messages in the status line. **Pause** (`ctrl+k`)
  pauses it.
- The tree above the log lists the message's fields. Untick fields to hide
  them from the echo; `ctrl+r` shows every field again.
- Echo picks a QoS that can hear every current publisher (best-effort if any
  publisher is best-effort). The QoS is fixed when the echo starts, so if a
  publisher with a different QoS appears later, restart the echo.
- Long arrays and strings are shortened, and at a high rate only the newest
  few messages per frame are drawn; the rest are counted as dropped.

## Services

Edit the request and press **Call** (`ctrl+s`). The response and the
round-trip time go into the log. If no server answers within 5 s, or no
response comes back within 30 s, you get an error.

## Actions

Edit the goal and press **Send goal** (`ctrl+s`). The status line goes
SENDING → EXECUTING → SUCCEEDED, ABORTED or CANCELED. Feedback streams into
the log (at a high rate, only some of it is drawn) and the result is printed
at the end. **Cancel** (`ctrl+k`) cancels the goal.

## Nodes

Opening a node shows two panes:

- **Interfaces**: its publishers, subscribers, service servers and clients,
  and action servers and clients, like `ros2 node info`. Select one to jump
  to it in the Topics, Services or Actions tab.
- **Parameters**: every parameter with its type and value. Highlight one,
  edit the value (as YAML) in the box below, and press **Set** (`ctrl+s`).
  **Refresh** (`ctrl+k`) reloads the node.

## The editor

The editor speaks the same YAML as `ros2 topic pub` and
`ros2 action send_goal`, prefilled with the message's defaults. Integer
constants defined in the message are listed in a comment above it. `tab` and
`shift+tab` jump between values.

- `stamp: now` fills a `builtin_interfaces/Time` with the current time when
  you send. `header: auto` sends a Header stamped with the current time. When
  publishing at a rate, both are filled in again for every message.
- `.nan`, `.inf` and `-.inf` work for floats, and strings can be any unicode.
- Everything is checked before it's sent: types, integer and float ranges,
  fixed array sizes and bounded sequence lengths. The error names the field,
  e.g. `pose.pose.position.x: could not convert string to float: 'oops'`. The
  stock ROS CLI is less strict: it silently sends `UInt8(data=300)` as a
  different number, for example.
- Message types are only loaded when you first open something that uses them,
  so ros_tui starts quickly even with thousands of interfaces installed.

### Field helpers

Put the cursor on a field and press `ctrl+w` (or the **Fill…** button) to fill
it in with a small form instead of typing YAML:

| Field                      | Helper                                                       |
| -------------------------- | ------------------------------------------------------------ |
| `std_msgs/Header`          | auto, now, or a manual stamp and `frame_id`                  |
| `builtin_interfaces/Time`  | seconds, a wall-clock date and time, or relative to now      |
| `geometry_msgs/Quaternion` | raw x/y/z/w, roll/pitch/yaw, yaw only, or axis and angle     |
| an integer with constants  | pick one of the message's constants (e.g. `level: OK/WARN/ERROR/STALE`) |

The innermost field with a helper wins: on `header.stamp` you get the Time
helper, on `header` the Header helper. Helpers work in the Services and
Actions editors, and in the Topics editor in publish mode.

## Key bindings

| Key                 | Does                                                                |
| ------------------- | ------------------------------------------------------------------- |
| `ctrl+t`            | next tab (Topics → Services → Actions → Nodes)                      |
| `ctrl+f`            | back to the list, with the filter box focused                       |
| `↑` / `↓`           | move through the matches while the filter box is focused            |
| `enter`             | open the highlighted match                                          |
| `ctrl+s`            | Publish or Echo / Call / Send goal / Set parameter                  |
| `ctrl+k`            | stop the rate publisher or pause the echo / Cancel goal / Refresh node |
| `ctrl+r`            | reset the editor to the defaults (Subscribe: show every field)      |
| `ctrl+w`            | open a helper for the field under the cursor                        |
| `tab` / `shift+tab` | next / previous value in the editor                                 |
| `ctrl+l`            | clear the log of the current tab                                    |
| `f2`                | help (`esc` closes it)                                              |
| `ctrl+q`            | quit                                                                |

The mouse works too: click tabs, list entries, buttons and tree nodes.

## Noisy RMW output

Some RMW implementations print warnings straight to the terminal, over the
UI. Send stderr to a file to keep the screen clean:

```bash
ros2 run ros_tui ros_tui 2>>/tmp/ros_tui.stderr
```
