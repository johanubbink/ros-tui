# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
