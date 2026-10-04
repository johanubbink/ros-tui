# Architecture

ros_tui is two layers joined by one rule: **only the ROS thread touches rclpy,
and only the UI thread touches textual.**

```
  UI thread (textual)                              ros-bridge thread (rclpy)
  ───────────────────                              ─────────────────────────
  RosTuiApp                                        private Context + Node
   ├─ TopicsTab ─┐                                  + SingleThreadedExecutor
   ├─ ServicesTab├─ bridge.call_service(...) ──>   command queue ──> guard condition
   ├─ ActionsTab ┘   returns a Future              (runs the command on this thread)
   └─ NodesTab                                      │
         ▲                                          ├─ clients / publishers (LRU cache)
         │  post_message(ServiceCompleted, ...)     ├─ subscriptions ──> EchoBuffer ──┐
         └──────────────────────────────────────────┤  housekeeping timer (4 Hz)    │
         │  drain() at 10 Hz                        └─ graph poll (1 Hz) ──> GraphSnapshot
         └──────────────────────────────────────────────────────────────────────────┘
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
    types, and checked YAML ↔ message conversion
    ([Messages and YAML](#messages-and-yaml)).
  - [`echo.py`](../ros_tui/ros/echo.py): `EchoBuffer`, the bounded hand-off of
    received messages to the UI.
  - [`events.py`](../ros_tui/ros/events.py): the action lifecycle events the
    bridge emits.
- [`ros_tui/ui/`](../ros_tui/ui/): the textual app. Nothing in here touches
  rclpy; it only calls `RosBridge` methods.
  - [`app.py`](../ros_tui/ui/app.py): `RosTuiApp`, the four tabs, the global
    key bindings and the help screen.
  - [`entity_tab.py`](../ros_tui/ui/entity_tab.py),
    [`interface_tab.py`](../ros_tui/ui/interface_tab.py): the tab base classes
    ([Tabs](#tabs)).
  - `topics_tab.py`, `services_tab.py`, `actions_tab.py`, `nodes_tab.py`: one
    module per tab.
  - [`messages.py`](../ros_tui/ui/messages.py): the textual messages that
    carry results from the ROS thread to the UI thread.
  - [`filterable_list.py`](../ros_tui/ui/filterable_list.py),
    [`message_editor.py`](../ros_tui/ui/message_editor.py),
    [`topic_mode_popup.py`](../ros_tui/ui/topic_mode_popup.py): shared widgets.
  - [`wizards/`](../ros_tui/ui/wizards/): the field helpers behind `ctrl+w`
    ([Field wizards](#field-wizards)).
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
  messages (`ServiceCompleted`, `ActionEventMessage`, `NodeParametersReady`,
  …).

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
- The Topics tab drains the buffer every 0.1 s (UI thread), draws at most 3
  messages per drain, and counts the rest as dropped. The status line shows
  the message count, the rate (over the last 64 messages) and the drop count.

Action feedback works the same way, with its own buffer and limits.

Echo picks its QoS from the publishers that exist when it starts
(`adapted_qos`): best-effort if any publisher is best-effort, so it can hear
all of them.

## Messages and YAML

[`message_yaml.py`](../ros_tui/ros/message_yaml.py) does the conversions in
both directions:

- **Loading types** is lazy: a message, service or action class is imported
  the first time it's opened, in a worker thread, and cached. That keeps
  startup fast on systems with thousands of interfaces.
- **Seeding the editor** (`default_yaml`): the default message as YAML, with
  the message's integer constants in a comment.
- **Building a message** (`build_message`): it re-implements
  `rosidl_runtime_py.set_message_fields`, because the Jazzy version neither
  says which field was wrong nor checks ranges and sizes (it would send
  `UInt8(data=300)` silently corrupted). Every (sub)message is built with
  `check_fields=True`, and every failure becomes a `FieldError` with the field
  path (`pose.position.x`, `points[1].x`). `stamp: now` and `header: auto` turn
  into time setters the bridge applies right before sending.
- **Showing a message** (`to_truncated_yaml`, `to_filtered_yaml`): YAML with
  long arrays and strings shortened and a line cap, optionally showing only
  the fields picked in the Topics tab's tree.
- **Message structure** (`message_structure`): a tree of `FieldNode`s (name,
  type, constants, children) read from the class. The Topics field tree and
  the field wizards use it.

## Tabs

Every tab is an `EntityTab`: a `FilterableList` on the left, a detail pane on
the right, and the hooks the app's key bindings call (`primary_action`,
`secondary_action`, `reset_editor`, `wizard_action`, `clear_log`,
`select_entity`). The app routes each global key to the active tab, so a tab
only has to fill in the hooks it supports.

`InterfaceTab` extends that for the three tabs with an editor (Topics,
Services, Actions): the type line, the `MessageEditor`, the controls row, a
status line and the output log. Subclasses add their own controls and verbs
through `compose_controls`, `compose_status` and the hooks above. Selecting an
entry loads its type in a worker thread and posts `PrototypeReady`; edits are
kept per entry, and `ctrl+r` restores the seed.

`NodesTab` is an `EntityTab` without an editor: an interfaces tree over a
parameter table. Selecting an interface posts `NavigateToEntity`, and the app
switches tab and selects that entity there.

The app polls nothing itself. The bridge's graph listener posts
`GraphUpdated`, and the app hands the new entries to each tab.

## Field wizards

`ctrl+w` finds the field under the editor's cursor (pure text helpers in
[`wizards/editing.py`](../ros_tui/ui/wizards/editing.py)), looks its type up
in the message structure, and opens the innermost matching wizard
([`wizards/registry.py`](../ros_tui/ui/wizards/registry.py)). A wizard is a
modal `WizardScreen` that returns the field's new value; the tab renders it
back into the editor in place of the old block.

Wizards register themselves with `@register('pkg/Type')` (Header, Time,
Quaternion). Integer fields with constants get the enum picker. Adding one is
described in [`wizards/__init__.py`](../ros_tui/ui/wizards/__init__.py).

## Shutdown

`ctrl+q` exits the app, and `main()` then calls `bridge.shutdown()`. That
clears the bridge's running flag (so `submit()` refuses new work) and wakes
the executor. The ROS thread leaves its spin loop and tears down: queued
commands are cancelled, parked and in-flight requests fail with "ROS bridge
shut down", and every timer (including periodic publishers), subscription,
publisher and client is destroyed, then the node and the context.
`shutdown()` waits up to 3 s for the thread to finish.
