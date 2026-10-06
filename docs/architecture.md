# Architecture

ros_tui is two layers joined by one rule: **only the ROS thread touches rclpy,
and only the UI thread touches textual.**

```
  UI thread (textual)                          ros-bridge thread (rclpy)
  ───────────────────                          ─────────────────────────
  RosTuiApp.on_key                             private Context + Node
   └─ NavState.handle_key (keymap.py)           + SingleThreadedExecutor
       └─ EntryRouter                            │
           ├─ TopicEntry  ─┐                     │
           ├─ ServiceEntry ├─ bridge.call_service(...) ──> command queue ──> guard condition
           ├─ ActionEntry  │  returns a Future   │         (runs the command on this thread)
           └─ NodeEntry   ─┘                     ├─ clients / publishers (LRU cache)
         ▲                                       ├─ subscriptions ──> EchoBuffer ──┐
         │  post(fn): a UiCall message           ├─ housekeeping timer (4 Hz)      │
         └───────────────────────────────────────┘  graph poll (1 Hz) ──> GraphSnapshot
         │  tick() every 0.1 s drains the echoes                                    │
         └──────────────────────────────────────────────────────────────────────────┘
  widgets/: views that redraw from the NavState after every key, answer and tick
```

[`ros_tui/main.py`](../ros_tui/main.py) starts the bridge, runs the app, and
shuts the bridge down when the app exits.

The code:

- [`ros_tui/ros/`](../ros_tui/ros/): everything that talks to ROS. Nothing in
  here imports textual.
  - [`bridge.py`](../ros_tui/ros/bridge.py): `RosBridge`, the thread that owns
    rclpy ([The bridge](#the-bridge)).
  - [`graph.py`](../ros_tui/ros/graph.py): immutable `GraphSnapshot`s of the
    topics, services, actions and nodes, and `NodeInfo` (a node's endpoints,
    like `ros2 node info`).
  - [`message_yaml.py`](../ros_tui/ros/message_yaml.py): loading interface
    types, the structure of a message, and checked plain data ↔ message
    conversion ([Messages](#messages)).
  - [`echo.py`](../ros_tui/ros/echo.py): `EchoBuffer`, the bounded hand-off of
    received messages to the UI.
  - [`events.py`](../ros_tui/ros/events.py): the action lifecycle events the
    bridge emits.
- [`ros_tui/ui/`](../ros_tui/ui/): the textual app ([The UI](#the-ui)). Nothing
  in here touches rclpy; it only calls `RosBridge` methods.
  - [`app.py`](../ros_tui/ui/app.py): `RosTuiApp`, one screen of views over the
    nav model, the one key router, the clock tick and the graph updates.
  - [`nav.py`](../ros_tui/ui/nav.py): `NavState`, the pure model of what is on
    screen: the ☰ list, the open tabs, the layer, the cursors, the overlays,
    undo, the toast and the activity lines.
  - [`keymap.py`](../ros_tui/ui/keymap.py): the one table of keys.
  - [`entries/`](../ros_tui/ui/entries/): one `EntryProvider` per entry kind
    (topic, service, action, node) and the `EntryRouter` that picks one.
  - [`fields.py`](../ros_tui/ui/fields.py): `FieldRows`, the model of a message
    as editable field rows.
  - [`helpers/`](../ros_tui/ui/helpers/): the field helpers (Quaternion,
    Header, Time, Enum) and their maths.
  - [`register.py`](../ros_tui/ui/register.py): the typed copy / paste register.
  - [`widgets/`](../ros_tui/ui/widgets/): the views, each drawing part of the
    `NavState`, and [`theme.py`](../ros_tui/ui/theme.py), the colours.
  - [`messages.py`](../ros_tui/ui/messages.py): the textual messages that
    carry results from the ROS thread to the UI thread.
- [`ros_tui/constants.py`](../ros_tui/constants.py): every rate, timeout and
  buffer size in one place.
- [`ros_tui/demo/demo_servers.py`](../ros_tui/demo/demo_servers.py) and
  [`launch/demo.launch.py`](../launch/demo.launch.py): the example servers used
  by the Docker playground and the GIF.

## The bridge

`RosBridge` starts one daemon thread, `ros-bridge`. That thread creates a
private rclpy `Context`, one node and a single-threaded executor, and spins
them until shutdown. Every rclpy entity (clients, publishers, subscriptions,
timers) is created and destroyed on that thread, because creating or
destroying entities from another thread races the executor's wait set.

The UI asks for work through the bridge's public methods (`call_service`,
`send_goal`, `publish_once`, `subscribe`, `list_node_parameters`, …). Each one
wraps the work in a closure and calls `submit()`, which puts it on a queue and
triggers a guard condition. The guard condition wakes the executor, which runs
the queued closures on the ROS thread.

Results come back in one of two ways:

- a `concurrent.futures.Future` the UI can watch, or
- a callback run on the ROS thread. Callbacks must be cheap and thread-safe;
  the UI's callbacks only call textual's `post_message`, which is safe from
  any thread. [`ui/messages.py`](../ros_tui/ui/messages.py) lists those
  messages: `GraphUpdated`, `PublisherCount`, and `UiCall`, which carries any
  entry's bridge answer as a function to run on the UI thread.

**Nothing blocks the ROS thread.** The bridge never waits for a server with
`wait_for_service`. A request whose server isn't up yet is parked, and a
**housekeeping timer** (4 Hz) checks parked requests and in-flight calls: a
server must appear within 5 s, and a response must arrive within 30 s, or the
request fails with a timeout.

**Clients and publishers are cached** per (name, type), so calling a service
twice reuses its client. The cache holds 8 entries and evicts the least
recently used one, skipping any entity still in use, so a long session doesn't
pile up DDS resources.

**Periodic publishing** is a timer per topic on the ROS thread. It keeps
running while the UI shows other topics, and the bridge destroys them all on
shutdown. `stamp: now` and `header: auto` fields are filled in again on every
tick.

**The graph** is polled once a second on the ROS thread into a
`GraphSnapshot`. The UI is only told when the snapshot differs from the last
one, so an idle system costs no redraws. Names ROS treats as hidden (any
`_`-prefixed part) and the services every node creates for itself
(parameters, type description) are left out.

## Fast data: echo and feedback

A topic can publish far faster than a terminal can draw. So received messages
never go straight to the UI:

- The subscription callback (ROS thread) pushes each message into an
  `EchoBuffer`: a lock-protected deque of 200. When it's full, the oldest
  message is dropped and counted.
- The app's clock tick (`UI_TICK_PERIOD_S`, 0.1 s, UI thread) drains the
  buffer and keeps only the newest message, converted once for display. The
  count, the rate (over the last 64 messages) and the drops still add up, and
  a 1 kHz topic costs one conversion per tick. The tick redraws only when the
  tab on screen shows something new, so an idle app never redraws.

Action feedback works the same way, with a buffer per goal.

Echo picks its QoS from the publishers that exist when it starts
(`adapted_qos`): best-effort if any publisher is best-effort, so it can hear
all of them.

## Messages

[`message_yaml.py`](../ros_tui/ros/message_yaml.py) does the conversions in
both directions:

- **Loading types** is lazy: a message, service or action class is imported
  the first time it's opened, in a worker thread, and cached. That keeps
  startup fast on systems with thousands of interfaces.
- **Message structure** (`message_structure`): a tree of `FieldNode`s (name,
  type, enum constants, children) read from the class. The field rows and the
  field helpers are built from it.
- **Plain data** (`message_to_plain`): a message as dicts, lists and scalars.
  It seeds an editor with the defaults (a nested Header as `auto`) and is what
  `y` copies. `message_to_display` is the same with long arrays and strings
  cut, for an echo or a goal's feedback.
- **Building a message** (`build_message`): it re-implements
  `rosidl_runtime_py.set_message_fields`, because the Jazzy version neither
  says which field was wrong nor checks ranges and sizes (it would send
  `UInt8(data=300)` silently corrupted). Every (sub)message is built with
  `check_fields=True`, and every failure becomes a `FieldError` with the field
  path (`pose.position.x`, `points[1].x`), which the UI maps to a row and an
  error line. `stamp: now` and `header: auto` turn into time setters the bridge
  applies right before sending.

## The UI

The UI is a pure model with thin views. The rules behind it, the keymap
rules, the look and the copy are in
[design-principles.md](design-principles.md); this is how the code fits
together.

- **The nav model.** [`nav.py`](../ros_tui/ui/nav.py)'s `NavState` holds
  everything on screen as plain Python (no textual, no rclpy): the catalogue
  for the ☰ list (fed from each `GraphSnapshot` by `set_catalog`), the open
  tabs, the layer (tab row › inside a tab › inside an area › insert), the
  cursors, the overlays (search, the command line, which-key, the field
  helper, `:log`), the undo stack (each change owned by the tab it was made
  in), the toast, the activity lines and
  the register. `footer()` says what the footer shows, `summary()` the same as
  data for the test harness. Its clock is the bridge's `now()`, so tests run it
  on a manual clock.
- **The keymap.** [`keymap.py`](../ros_tui/ui/keymap.py)'s `KEYMAP` is one
  table of `Binding`s: an input mode, the context predicates it applies in, the
  keys and the `NavState` action they run, and the label the footer, `?` and
  [usage.md](usage.md) show. `NavState.handle_key` looks a key up there and
  runs its action from `nav.ACTIONS`.
- **One key router.** [`app.py`](../ros_tui/ui/app.py)'s `RosTuiApp` has a
  single `on_key` that hands every key to `NavState.handle_key`, then redraws.
  Nothing takes focus, and textual's own bindings (focus cycling, the command
  palette) are off, so what a key does depends only on the model. Only
  `ctrl+q` and `ctrl+c` are bound, to quit.
- **Entries.** What an open entry holds and does comes from an
  `EntryProvider`: its areas, rows, edits, verbs (space, `s`, `r`, `e`, `y`,
  `p`, …), undo, running markers and tick. The app's provider is
  [`entries.EntryRouter`](../ros_tui/ui/entries/__init__.py), which hands each
  call to the kind's provider: `TopicEntry` (Echo / Publish, the echo, the
  repeat), `ServiceEntry`, `ActionEntry` (one goal at a time) and `NodeEntry`
  (interfaces and parameters). The three with a message to fill in share
  `MessageEntry` (the field-row editor, `[ ]` history, copy and paste, the
  helpers). An entry calls the bridge itself and wraps each answer in
  `post(fn)`, which the app turns into a `UiCall` message, so the answer is
  applied on the UI thread; a slow import runs through `work(fn)` in a textual
  thread worker. Entries are plain Python too.
- **Widgets.** [`widgets/`](../ros_tui/ui/widgets/) holds the views. Each is a
  `NavView` that draws part of the `NavState` as lines of Rich text and decides
  nothing: the top bar, the tab row, the ☰ list, the entry body (a header, a
  toolbar and one `Panel` per area, by a renderer per kind), the activity strip
  and the footer. Popups (search, `:log`, the command suggestions, which-key,
  the field helper, the toast) are `Overlay`s that say where they go. After
  each key, bridge answer or tick that changed something, the app's
  `refresh_views()` places the overlays and redraws every view.

## Shutdown

`:q` (or `ctrl+q`) exits the app, and `main()` then calls `bridge.shutdown()`.
That clears the bridge's running flag (so `submit()` refuses new work) and
wakes the executor. The ROS thread leaves its spin loop and tears down: queued
commands are cancelled, and parked and in-flight requests fail with "ROS
bridge shut down". Then every running goal is canceled, as `ros2 action
send_goal` does on ctrl+c, so nothing keeps acting on the robot after you quit:
the thread spins for at most `SHUTDOWN_CANCEL_TIMEOUT_S` (1 s) until each
server answered the cancel (a goal still waiting for acceptance is canceled
when it is accepted). Then every timer (including periodic publishers),
subscription, publisher and client is destroyed, then the node and the context.
`shutdown()` waits up to 3 s for the thread to finish.
