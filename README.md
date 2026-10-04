# ros_tui

ros_tui is a terminal UI for poking at a running ROS 2 system. Browse its
**topics, services, actions and nodes**, fill in a message in a prefilled YAML
editor, and publish, echo, call, send goals or set parameters, without typing
`ros2 ... "{...}"` one-liners.

![ros_tui against the demo servers: filtering the topic list, echoing a topic, calling a service and sending an action goal](assets/ros-tui-demo.gif)

## Install

ros_tui is a ROS 2 (ament_python) package. It isn't released to the ROS
buildfarm yet, so build it from source in a colcon workspace:

```bash
mkdir -p ~/ros_tui_ws/src && cd ~/ros_tui_ws/src
git clone https://github.com/johanubbink/ros-tui.git
cd ~/ros_tui_ws
rosdep install --from-paths src --ignore-src -y
pip install --user --upgrade --break-system-packages textual rich
colcon build --packages-select ros_tui
source install/setup.bash
```

The `pip` line (from `python3-pip`) is needed because the `textual` in Ubuntu's
apt is far too old. ros_tui is developed and tested on ROS 2 Jazzy (Ubuntu
24.04).

## Run it

```bash
ros2 run ros_tui ros_tui
```

The lists fill in from the live ROS graph and stay up to date. If a noisy RMW
prints warnings over the UI, send them elsewhere:
`ros2 run ros_tui ros_tui 2>>/tmp/ros_tui.stderr`.

## Using it

Each tab starts as a list you can filter. Type to filter, then `enter` to open
an entry. `ctrl+f` takes you back to the list.

- **Topics**: choose **Publish** or **Subscribe** when you open a topic.
  Publish once, or at a fixed rate. Echo shows the messages with Hz and drop
  counters, and you can pick which fields to show.
- **Services**: edit the request and **Call**. You get the response and the
  round-trip time.
- **Actions**: edit the goal and **Send goal**. Feedback streams into the
  log until the result arrives. **Cancel** cancels it.
- **Nodes**: see a node's publishers, subscribers, services and actions (jump
  to any of them), and view or set its parameters.

The editor uses the same YAML as `ros2 topic pub`, prefilled with the
message's defaults. `stamp: now` and `header: auto` are filled in at send
time. Everything is checked before it's sent, and errors name the field
(`pose.position.x: could not convert string to float: 'oops'`). Put the cursor
on a Header, Time, Quaternion or enum field and press `ctrl+w` for a helper to
fill it in.

| Key      | Does                                                         |
| -------- | ------------------------------------------------------------ |
| `ctrl+t` | next tab                                                     |
| `ctrl+f` | back to the list                                             |
| `ctrl+s` | Publish or Echo / Call / Send goal / Set parameter           |
| `ctrl+k` | stop publishing or pause echo / Cancel goal / Refresh node   |
| `ctrl+r` | reset the editor to the message defaults                     |
| `ctrl+w` | open a helper for the field under the cursor                 |
| `ctrl+l` | clear the log                                                |
| `f2`     | help                                                         |
| `ctrl+q` | quit                                                         |

The mouse works too. More detail is in [docs/usage.md](docs/usage.md).

## Try it without a robot

The repo includes a Docker playground with some example servers. You only need
Docker with the Compose plugin; ROS isn't needed on the host.

```bash
docker/create_dot_env            # once: matches the container user to yours
docker compose up --build        # builds, then starts the demo servers
docker compose exec ros_tui bash # in a second terminal...
ros2 run ros_tui ros_tui         # ...then run the TUI inside it
```

You can also run turtlesim with it (needs X11). See
[docs/docker.md](docs/docker.md) for that and for what to try in each tab.

## Docs

- [docs/usage.md](docs/usage.md): each tab, the editor, the field helpers
  and every key binding.
- [docs/docker.md](docs/docker.md): the Docker playground, the demo servers
  and turtlesim.
- [docs/architecture.md](docs/architecture.md): how ros_tui works inside.
- [docs/testing.md](docs/testing.md): running the tests, and
  `scripts/make_gif.py`, which remakes the GIF above.

## License

ros_tui is released under the Apache License 2.0. See [LICENSE](LICENSE).
