#!/usr/bin/env python3
# Copyright 2026 Johan Ubbink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Regenerate the README's demo GIF. Opt-in and dev-only, not part of the test suite; see
docs/testing.md, "Demo GIF".

    docker compose run --rm ros_tui src/ros_tui/scripts/make_gif.py

Starts the demo servers on a private ROS_DOMAIN_ID, runs the real app (real bridge) headless
under textual's Pilot, and drives it with key presses: echo /chatter, call /add_two_ints,
send a /fibonacci goal, open the demo node. A background task saves an SVG screenshot every
1/FPS s with the time it was taken; rsvg-convert turns them into PNGs and ffmpeg lays them out
at their real pace (one GIF frame per change, each held for as long as it lasted) and quantises
with one palette for the whole GIF (no dithering, so no flicker).

Needs ``rsvg-convert`` and ``ffmpeg`` (in the playground:
``sudo apt-get update && sudo apt-get install -y librsvg2-bin ffmpeg fonts-firacode``).
"""

import argparse
import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Before rclpy loads: keep the demo servers and the app away from any other ROS graph.
os.environ['ROS_DOMAIN_ID'] = os.environ.get('ROS_TUI_GIF_DOMAIN_ID', '87')

from ros_tui.ros.bridge import RosBridge  # noqa: E402
from ros_tui.ui.app import RosTuiApp  # noqa: E402
from ros_tui.ui.topic_mode_popup import TopicModePopup  # noqa: E402
from textual.widgets import DataTable, RichLog, Static, TextArea  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / 'assets' / 'ros-tui-demo.gif'

COLUMNS, ROWS = 124, 32
FPS = 10
GIF_WIDTH = 1000          # px; ffmpeg scales the rendered frames down to this
TYPE_DELAY_S = 0.11       # between key presses while "typing"


class Recorder:
    """Screenshots the app every 1/FPS s, keeping (time, svg) pairs."""

    def __init__(self, app):
        self._app = app
        self.frames: list[tuple[float, str]] = []
        self._task = None

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self.frames.append((time.monotonic(), self._app.export_screenshot()))

    async def _run(self):
        while True:
            self.frames.append((time.monotonic(), self._app.export_screenshot()))
            await asyncio.sleep(1 / FPS)


async def wait_until(pilot, predicate, timeout=10.0, what='condition'):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await pilot.pause(0.05)
    raise TimeoutError(f'timed out waiting for {what}')


async def type_text(pilot, text):
    for char in text:
        await pilot.press('space' if char == ' ' else char)
        await asyncio.sleep(TYPE_DELAY_S)


def static_text(widget):
    return str(widget.render())


async def filter_and_open(pilot, filter_text):
    """Type into the focused filter box (the first match is highlighted), then press enter."""
    await type_text(pilot, filter_text)
    await asyncio.sleep(0.5)
    await pilot.press('enter')


async def open_editor_entry(pilot, tab, filter_text, name):
    """Open ``name`` on a Services/Actions tab and put the cursor in its editor."""
    await filter_and_open(pilot, filter_text)
    await wait_until(pilot, lambda: name in tab._seed_cache, what=f'{name} to load')
    tab.query_one('#editor', TextArea).focus()
    await asyncio.sleep(0.6)


async def fill_value(pilot, value):
    """Replace the value under the editor's cursor (to end of line) with ``value``."""
    await pilot.press('shift+end')
    await asyncio.sleep(0.2)
    await type_text(pilot, value)


async def demo(pilot):
    app = pilot.app
    topics = app.query_one('#topics-tab')
    services = app.query_one('#services-tab')
    actions = app.query_one('#actions-tab')
    nodes = app.query_one('#nodes-tab')

    bridge = app._bridge
    await wait_until(pilot, lambda: any(e.name == '/fibonacci' for e in bridge.latest_graph.actions),
                     timeout=20.0, what='the demo servers')
    await asyncio.sleep(1.5)

    # Topics: echo /chatter.
    await filter_and_open(pilot, 'chat')
    await wait_until(pilot, lambda: isinstance(app.screen, TopicModePopup), what='mode popup')
    await asyncio.sleep(1.2)
    await pilot.press('s')
    await wait_until(pilot, lambda: '/chatter' in topics._seed_cache, what='/chatter to load')
    await asyncio.sleep(0.6)
    await pilot.press('ctrl+s')
    await asyncio.sleep(4.5)
    await pilot.press('ctrl+s')
    await asyncio.sleep(0.6)

    # Services: call /add_two_ints with 19 + 23.
    await pilot.press('ctrl+t')
    await asyncio.sleep(0.6)
    await open_editor_entry(pilot, services, 'add', '/add_two_ints')
    await fill_value(pilot, '19')
    await pilot.press('tab')
    await asyncio.sleep(0.3)
    await fill_value(pilot, '23')
    await asyncio.sleep(0.6)
    await pilot.press('ctrl+s')
    await wait_until(pilot, lambda: 'sum' in _log_text(services), what='the service response')
    await asyncio.sleep(2.0)

    # Actions: send a /fibonacci goal and watch the feedback until it succeeds.
    await pilot.press('ctrl+t')
    await asyncio.sleep(0.6)
    await open_editor_entry(pilot, actions, 'fib', '/fibonacci')
    await fill_value(pilot, '10')
    await asyncio.sleep(0.6)
    await pilot.press('ctrl+s')
    status = actions.query_one('#goal-status', Static)
    await wait_until(pilot, lambda: 'SUCCEEDED' in static_text(status), timeout=20.0,
                     what='the goal to succeed')
    await asyncio.sleep(2.0)

    # Nodes: the demo node's interfaces and parameters.
    await pilot.press('ctrl+t')
    await asyncio.sleep(0.6)
    await filter_and_open(pilot, 'demo')
    table = nodes.query_one('#node-params', DataTable)
    await wait_until(pilot, lambda: table.row_count > 0, what='the node parameters')
    await asyncio.sleep(3.0)


def _log_text(tab):
    return '\n'.join(strip.text for strip in tab.query_one('#output-log', RichLog).lines)


async def record() -> list[tuple[float, str]]:
    bridge = RosBridge()
    bridge.start()
    try:
        app = RosTuiApp(bridge)
        async with app.run_test(size=(COLUMNS, ROWS)) as pilot:
            recorder = Recorder(app)
            recorder.start()
            await demo(pilot)
            await recorder.stop()
            return recorder.frames
    finally:
        bridge.shutdown()


def encode(frames: list[tuple[float, str]], output: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Merge runs of identical frames: fewer PNGs to render, same timing.
        kept: list[tuple[float, str]] = []
        for stamp, svg in frames:
            if not kept or svg != kept[-1][1]:
                kept.append((stamp, svg))
        end = frames[-1][0] + 1.5  # hold the last frame before looping
        lines = []
        for index, (stamp, svg) in enumerate(kept):
            svg_path, png_path = tmp / f'{index:05d}.svg', tmp / f'{index:05d}.png'
            # Textual pads with leading spaces inside spans; keep rsvg from collapsing them.
            svg_path.write_text(svg.replace("<svg ", "<svg xml:space=\"preserve\" ", 1))
            subprocess.run(['rsvg-convert', '-o', str(png_path), str(svg_path)], check=True)
            following = kept[index + 1][0] if index + 1 < len(kept) else end
            lines += [f"file '{png_path}'", f'duration {following - stamp:.3f}']
        lines.append(f"file '{tmp / f'{len(kept) - 1:05d}.png'}'")  # concat needs the last twice
        (tmp / 'frames.txt').write_text('\n'.join(lines) + '\n')
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            'ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(tmp / 'frames.txt'),
            '-vf', (f'scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];'
                    '[a]palettegen=max_colors=64:stats_mode=full[p];[b][p]paletteuse=dither=none'),
            '-fps_mode', 'vfr', '-loop', '0', str(output),
        ], check=True)
        print(f'wrote {output} ({len(kept)} distinct frames, {output.stat().st_size // 1024} KiB)')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('-o', '--output', type=Path, default=OUTPUT)
    args = parser.parse_args()

    missing = [tool for tool in ('rsvg-convert', 'ffmpeg') if shutil.which(tool) is None]
    if missing:
        sys.exit(f'missing {", ".join(missing)}; see this script\'s docstring')

    servers = subprocess.Popen(['ros2', 'run', 'ros_tui', 'demo_servers'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        frames = asyncio.run(record())
    finally:
        os.killpg(servers.pid, signal.SIGINT)
        servers.wait(timeout=10)
    encode(frames, args.output)


if __name__ == '__main__':
    main()
