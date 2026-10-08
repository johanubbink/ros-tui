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
under the test harness's UiSession (test/harness/screens.py), and drives it with key presses at a
pace a viewer can follow: echo /chatter (and freeze it), call
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

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'test'))  # The harness's session and its SVG fix for rsvg.

from harness.screens import UiSession, rsvg_ready  # noqa: E402
from ros_tui.ros.bridge import RosBridge  # noqa: E402
from ros_tui.ui.app import RosTuiApp  # noqa: E402
from ros_tui.ui.nav import Tab  # noqa: E402

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


class GifSession(UiSession):
    """A UiSession that pauses after each key (in real time), so each step can be followed."""

    async def keys(self, *keys, pause=KEY_DELAY_S):
        for key in keys:
            await super().keys(key)
            await asyncio.sleep(pause)

    async def type_text(self, text):
        for char in text:
            await self.keys('space' if char == ' ' else char, pause=TYPE_DELAY_S)

    async def need(self, predicate, timeout=10.0, what='condition'):
        """Wait until ``predicate`` holds, or fail saying ``what`` never happened."""
        if not await self.wait_until(predicate, timeout):
            raise TimeoutError(f'timed out waiting for {what}')

    async def open_entry(self, query):
        """/ search for ``query`` and open the first match in a tab."""
        await self.keys('slash')
        await self.type_text(query)
        await asyncio.sleep(0.4)
        await self.keys('enter')


def activity(app, text):
    """True once an activity line contains ``text``."""
    return any(text in line.text for line in app.nav.feedback.activity)


async def demo(s: GifSession):
    app = s.app
    nav = app.nav

    def published(name):
        return any(item.name == name and item.publishers for item in nav.catalog['topics'])

    await s.need(lambda: published('/chatter') and nav.catalog['actions'], timeout=20.0, what='the demo servers')
    await asyncio.sleep(1.5)

    # A topic: /chatter opens in Echo; space echoes it, enter freezes it, esc goes live.
    await s.open_entry('chat')
    await s.keys('space', pause=4.0)
    await s.keys('enter', pause=2.5)
    await s.keys('escape', pause=1.5)
    await s.keys('space')

    # A service: /add_two_ints with 19 + 23.
    await s.open_entry('add')
    await s.keys('enter', 'enter')
    await s.type_text('19')
    await s.keys('tab')
    await s.type_text('23')
    await s.keys('escape', 'space')
    await s.need(lambda: activity(app, '✓ response'), what='the service response')
    await asyncio.sleep(2.0)

    # An action: send a /fibonacci goal and watch the feedback until it succeeds.
    await s.open_entry('fib')
    await s.keys('enter', 'enter')
    await s.type_text('10')
    await s.keys('escape', 'space')
    await s.need(lambda: activity(app, '✓ goal succeeded'), timeout=20.0, what='the goal to succeed')
    await asyncio.sleep(2.0)

    # A node: change the demo node's publish_rate, then set it.
    await s.open_entry('demo_servers')
    node = Tab('nodes', '/ros_tui_demo_servers')
    data = nav.entry(node)
    await s.need(lambda: data.params, what='the node parameters')
    await asyncio.sleep(1.5)
    row = [param.name for param in data.params].index('publish_rate')
    await s.keys('l', 'enter', *['j'] * row, 'c')
    await s.type_text('5')
    await s.keys('enter', pause=1.5)
    await s.keys('space')
    await s.need(lambda: activity(app, '✓ set publish_rate'), what='the parameter to be set')
    await asyncio.sleep(3.0)


async def record() -> list[tuple[float, str]]:
    bridge = RosBridge()
    bridge.start()
    try:
        app = RosTuiApp(bridge)
        async with app.run_test(size=(COLUMNS, ROWS)) as pilot:
            recorder = Recorder(app)
            recorder.start()
            await demo(GifSession(app, pilot, bridge, 'make_gif'))
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
            svg_path.write_text(rsvg_ready(svg))
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

    servers = subprocess.Popen([sys.executable, str(REPO_ROOT / 'docker' / 'demo_servers.py')],
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
