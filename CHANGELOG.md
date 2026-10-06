# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The "Hybrid Keys" redesign: the four-tab UI is replaced by a keyboard-first one
built on a layer model. Rationale and rules: [docs/design-principles.md](docs/design-principles.md);
every key: [docs/usage.md](docs/usage.md).

### Changed
- **One ☰ list and a tab per entry** instead of the Topics, Services, Actions
  and Nodes tabs with their list panes. The list mixes every kind, with chips
  (`tab`, `:topics` …) to filter it; `/` searches everything; an opened entry
  gets the full width (there is no sidebar). Open entries stay as tabs (`0`…`9`,
  `H` `L`, `x`).
- **Layers instead of focus.** The tab row › inside a tab › inside an area ›
  insert: `esc` always goes up one layer and `enter` down one, and the footer
  always says which layer you're on and what `esc` and `enter` do. A key's
  meaning depends only on the layer and the entry, never on focus. `?` lists
  every key that works right now; `:` opens a command line.
- **Field rows instead of the YAML editor.** Messages are edited one field
  per row (fold and unfold nested messages, `o` / `d` add and delete list
  elements), checked as you type, with the error under the panel naming the
  field.
- **Field helpers** open with `f` on a field that shows `[f …]`, under the
  row, instead of `ctrl+w` and a modal screen.
- **Topics** open in Echo when someone publishes them and in Publish when
  nobody does (`e` switches), instead of asking. Going into an echo freezes it;
  `esc` goes live again.
- **Nodes** show changed parameters until space sets them all.
- The keys: `ctrl+t`, `ctrl+k`, `ctrl+r`, `ctrl+w`, `ctrl+l` and `f2` are
  gone. `ctrl+s` stays as an alias of space, `ctrl+f` now opens search (as `/`
  does), and `ctrl+q` still quits (as does `:q`). The mouse is no longer used.

### Added
- **Only space and `^s` send.** Space publishes once, calls, sends the goal,
  sets the changed parameters, or starts and stops an echo. The prototype's
  `.` (resend the last send) was dropped, so no other key sends what's in the
  editor. **`r` repeats** a publish at the shown rate (`R` or `:rate 5`
  changes it) and **`s` stops**: it stops a repeat or cancels a goal, and
  never sends.
- **`u` undoes per tab**: edits, pastes, applied helpers, rate and parameter
  changes, in the tab they were made in; right after `x` it reopens the closed
  tab. With nothing to undo it says `nothing to undo here`.
- `y` / `p`: a typed copy / paste register (a message, a request or a goal)
  across entries of the same type; `y` in Echo copies the message exactly as
  it arrived.
- `[` / `]`: the history of what you sent from an entry.
- An activity strip above the footer with the time of every send and result,
  and `:log` for all of it.
- Echoes, repeats and running goals keep going in other tabs, shown in the top
  bar and the ☰ list.

### Fixed
- Quitting cancels every running goal (as `ros2 action send_goal` does on
  ctrl+c), waiting up to 1 s for the servers, as well as stopping repeats and
  echoes, so nothing keeps acting on the robot after you quit.

## [0.1.0] - 2026-10-04

Initial release.

### Added
- `ros2 run ros_tui ros_tui`: a terminal UI for a live ROS 2 system, with
  **Topics**, **Services**, **Actions** and **Nodes** tabs, each a filterable
  list that follows the ROS graph.
- **Topics**: publish once or at a fixed rate (0.1–100 Hz, kept running in
  the background), or echo with Hz and drop counters, a QoS that matches the
  publishers, and a field picker for what to show.
- **Services**: call with an edited request; see the response and round-trip
  time.
- **Actions**: send a goal, watch its status and feedback, see the result,
  cancel it.
- **Nodes**: a node's publishers, subscribers, services and actions (jump to
  any of them), and its parameters, which can be set.
- **A YAML editor** prefilled with the message's defaults, with `stamp: now`
  and `header: auto`, `tab` to jump between values, and checks for types,
  ranges and sizes that name the field at fault.
- **Field helpers** (`ctrl+w`) for Header, Time, Quaternion and integer enum
  fields.
- **A Docker playground** with demo servers and optional turtlesim
  (`compose.yaml`, `launch/demo.launch.py`).

[Unreleased]: https://github.com/johanubbink/ros-tui/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/johanubbink/ros-tui/releases/tag/v0.1.0
