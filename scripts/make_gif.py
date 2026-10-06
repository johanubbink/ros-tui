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
under textual's Pilot, and drives it with key presses: echo /chatter (and freeze it), call
/add_two_ints, send a /fibonacci goal, change and set a parameter of the demo node. A background
task saves an SVG screenshot every 1/FPS s with the time it was taken; rsvg-convert turns them into
PNGs (on BACKGROUND, so the window's rounded corners are opaque) and ffmpeg lays them out at their
real pace (one GIF frame per change, each held for as long as it lasted) and quantises with one
palette for the whole GIF (no dithering, so no flicker).

Needs ``rsvg-convert`` and ``ffmpeg`` (the playground has the first; for the second:
``sudo apt-get update && sudo apt-get install -y ffmpeg``).
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
from ros_tui.ui.nav import Tab  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / 'assets' / 'ros-tui-demo.gif'

COLUMNS, ROWS = 124, 34
FPS = 10
GIF_WIDTH = 1000          # px; ffmpeg scales the rendered frames down to this
# Behind the window's rounded corners. With any transparency, ffmpeg (6.x) can't store only what
# changed in a GIF frame, so every frame would be a full one (4 MB instead of under 1 MB).
BACKGROUND = '#121212'
TYPE_DELAY_S = 0.11       # between key presses while "typing"
KEY_DELAY_S = 0.5         # between the other key presses, so each step can be followed


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


async def keys(pilot, *names, pause=KEY_DELAY_S):
    """Press textual key names one by one, pausing after each."""
    for name in names:
        await pilot.press(name)
        await asyncio.sleep(pause)


async def open_entry(pilot, query):
    """/ search for ``query`` and open the first match in a tab."""
    await keys(pilot, 'slash')
    await type_text(pilot, query)
    await asyncio.sleep(0.4)
    await keys(pilot, 'enter')


def activity(app, text):
    """True once an activity line contains ``text``."""
    return any(text in line.text for line in app.nav.activity)


async def demo(pilot):
    app = pilot.app
    nav = app.nav

    def published(name):
        return any(item.name == name and item.publishers for item in nav.catalog['topics'])

    await wait_until(pilot, lambda: published('/chatter') and nav.catalog['actions'],
                     timeout=20.0, what='the demo servers')
    await asyncio.sleep(1.5)

    # A topic: /chatter opens in Echo; space echoes it, enter freezes it, esc goes live.
    await open_entry(pilot, 'chat')
    await keys(pilot, 'space', pause=4.0)
    await keys(pilot, 'enter', pause=2.5)
    await keys(pilot, 'escape', pause=1.5)
    await keys(pilot, 'space')

    # A service: /add_two_ints with 19 + 23.
    await open_entry(pilot, 'add')
    await keys(pilot, 'enter', 'enter')
    await type_text(pilot, '19')
    await keys(pilot, 'tab')
    await type_text(pilot, '23')
    await keys(pilot, 'escape', 'space')
    await wait_until(pilot, lambda: activity(app, '✓ response'), what='the service response')
    await asyncio.sleep(2.0)

    # An action: send a /fibonacci goal and watch the feedback until it succeeds.
    await open_entry(pilot, 'fib')
    await keys(pilot, 'enter', 'enter')
    await type_text(pilot, '10')
    await keys(pilot, 'escape', 'space')
    await wait_until(pilot, lambda: activity(app, '✓ goal succeeded'), timeout=20.0, what='the goal to succeed')
    await asyncio.sleep(2.0)

    # A node: change the demo node's publish_rate, then set it.
    await open_entry(pilot, 'demo_servers')
    node = Tab('nodes', '/ros_tui_demo_servers')
    data = nav.provider.for_tab(node).data(node)
    await wait_until(pilot, lambda: data.params, what='the node parameters')
    await asyncio.sleep(1.5)
    row = [param.name for param in data.params].index('publish_rate')
    await keys(pilot, 'l', 'enter', *['j'] * row, 'c')
    await type_text(pilot, '5')
    await keys(pilot, 'enter', pause=1.5)
    await keys(pilot, 'space')
    await wait_until(pilot, lambda: activity(app, '✓ set publish_rate'), what='the parameter to be set')
    await asyncio.sleep(3.0)


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


def for_rsvg(svg: str) -> str:
    """Textual's SVG made to render in rsvg as it does in a browser (as test/harness/screens.py does)."""
    # Textual pads with leading spaces inside spans; keep rsvg from collapsing them.
    svg = svg.replace('<svg ', '<svg xml:space="preserve" ', 1)
    # Its web font (Fira Code from a CDN) is unreachable for rsvg: name the installed design font,
    # and match its glyph advance (0.6 em) to textual's 12.2 px cell so long runs don't drift.
    svg = svg.replace('font-family: Fira Code,', 'font-family: JetBrains Mono, Fira Code,')
    return svg.replace('font-size: 20px', 'font-size: 20.333px')


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
            svg_path.write_text(for_rsvg(svg))
            subprocess.run(['rsvg-convert', '-b', BACKGROUND, '-o', str(png_path), str(svg_path)], check=True)
            following = kept[index + 1][0] if index + 1 < len(kept) else end
            lines += [f"file '{png_path}'", f'duration {following - stamp:.3f}']
        lines.append(f"file '{tmp / f'{len(kept) - 1:05d}.png'}'")  # concat needs the last twice
        (tmp / 'frames.txt').write_text('\n'.join(lines) + '\n')
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            'ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(tmp / 'frames.txt'),
            '-vf', (f'scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];'
                    '[a]palettegen=max_colors=64:stats_mode=full:reserve_transparent=0[p];'
                    '[b][p]paletteuse=dither=none'),
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
