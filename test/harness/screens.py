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

"""Drive the app headless and take named screenshots for agents to compare with the design.

    async with ui_session() as s:                 # FakeBridge.demo(), 124x34 terminal
        await s.keys('c', 'h', 'a', 't', 'enter')
        await s.advance(2.0)                      # simulated seconds (the bridge's ManualClock)
        await s.shot('echo-live', expect='/chatter echoing, chatter 1 and chatter 2 visible')

Every ``shot()`` records the screen text and a state summary in ``s.shots``. With
``ROS_TUI_SHOTS=1`` it also writes, into ``test/artifacts/<test id>/``:

- ``NN-name.svg``: textual's own screenshot (``App.export_screenshot``),
- ``NN-name.png``: the SVG rendered by ``rsvg-convert`` (skipped, with a warning, if missing),
- ``NN-name.txt``: the screen as plain text,
- ``NN-name.json``: the state (screen, focus, active tab, toasts, plus whatever the app's optional
  ``harness_state()`` hook returns), the keys pressed so far and the ``expect`` text,
- a section in ``manifest.md`` with the keys and the ``expect`` text.

See docs/agentic-dev.md.
"""

import io
import json
import os
import re
import shutil
import subprocess
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from harness.fake_bridge import FakeBridge
from rich.console import Console
from ros_tui.constants import ECHO_RENDER_PERIOD_S
from ros_tui.ui.app import RosTuiApp
from textual.widgets import TabbedContent

ARTIFACTS_ROOT = Path(__file__).resolve().parents[1] / 'artifacts'
SHOTS_ENV = 'ROS_TUI_SHOTS'
DEFAULT_SIZE = (124, 34)
SETTLE_TIMEOUT_S = 2.0  # Real time allowed for the UI to drain what one clock step produced.


def shots_enabled() -> bool:
    return os.environ.get(SHOTS_ENV) == '1'


def artifact_dir_name(test_id: str) -> str:
    """'test/ui/test_x.py::test_y[a]' -> 'ui__test_x__test_y_a_' (one folder per test)."""
    name = test_id.removeprefix('test/').replace('.py', '').replace('::', '__').replace('/', '__')
    return re.sub(r'[^A-Za-z0-9_.-]', '_', name)


def current_test_id() -> str:
    return os.environ.get('PYTEST_CURRENT_TEST', 'adhoc').split(' ')[0]


class UiSession:
    """One running app under Pilot plus the shots taken of it."""

    def __init__(self, app, pilot, bridge, test_id: str):
        self.app = app
        self.pilot = pilot
        self.bridge = bridge
        self.test_id = test_id
        self.steps: list[str] = []  # Keys pressed and clock advances, in order.
        self.shots: list[dict[str, Any]] = []
        self.directory = ARTIFACTS_ROOT / artifact_dir_name(test_id)
        self._steps_at_last_shot = 0
        if shots_enabled():
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory.mkdir(parents=True)
            (self.directory / 'manifest.md').write_text(f'# {test_id}\n')

    # ---------------------------------------------------------------- driving

    async def idle(self) -> None:
        """Let the app process everything queued: messages, workers, the refresh after them."""
        await self.pilot.pause()
        await self.app.workers.wait_for_complete()
        await self.pilot.pause()

    async def keys(self, *keys: str) -> None:
        """Press keys one at a time (textual key names), letting the app go idle after each."""
        for key in keys:
            await self.pilot.press(key)
            self.steps.append(key)
            await self.idle()

    async def type_text(self, text: str) -> None:
        """Type ``text`` character by character (Pilot accepts single characters as keys)."""
        await self.keys(*('space' if char == ' ' else char for char in text))

    async def wait_until(self, predicate: Callable[[], Any], timeout: float = 5.0) -> bool:
        """Poll ``predicate`` in real time (for the UI's own timers, e.g. a filter debounce)."""
        waited = 0.0
        while not predicate() and waited < timeout:
            await self.pilot.pause(0.05)
            waited += 0.05
        await self.idle()
        return bool(predicate())

    async def advance(self, seconds: float, step: float = ECHO_RENDER_PERIOD_S) -> None:
        """Advance the fake bridge's clock by ``seconds`` in ``step``s, letting the UI keep up.

        After each step the UI gets (real) time to drain what the step pushed into echo buffers,
        so a 1 Hz topic shows every message, the way it would in real time.
        """
        clock = getattr(self.bridge, 'clock', None)
        if clock is None:
            raise TypeError('advance() needs a bridge with a ManualClock (FakeBridge)')
        remaining = seconds
        while remaining > 1e-9:
            delta = min(step, remaining)
            clock.advance(delta)
            remaining -= delta
            await self._settle()
        # Action feedback and similar buffers drain on the UI's own 10 Hz timer.
        await self.pilot.pause(ECHO_RENDER_PERIOD_S * 1.5)
        await self.idle()
        self.steps.append(f'+{seconds:g}s')

    async def _settle(self) -> None:
        await self.idle()
        pending = getattr(self.bridge, 'pending_echo', lambda: 0)
        waited = 0.0
        while pending() and waited < SETTLE_TIMEOUT_S:
            await self.pilot.pause(0.02)
            waited += 0.02
        await self.idle()

    # ---------------------------------------------------------------- looking

    def text(self) -> str:
        """The screen as plain text (what ``NN-name.txt`` holds)."""
        return self._render_console().export_text(clear=False)

    def state(self) -> dict[str, Any]:
        """A JSON-able summary of where the UI is; the app may add to it via ``harness_state()``."""
        app = self.app
        focused = app.focused
        tabbed = list(app.screen_stack[0].query(TabbedContent))
        state = {
            'screen': type(app.screen).__name__,
            'screen_stack': [type(screen).__name__ for screen in app.screen_stack],
            'focused': None if focused is None else {
                'id': focused.id, 'class': type(focused).__name__,
            },
            'active_tab': tabbed[0].active if tabbed else None,
            # textual has no public accessor for live notifications (the toast rack lags a frame).
            'toasts': [
                {'message': str(note.message), 'severity': note.severity}
                for note in getattr(app, '_notifications', ())
            ],
        }
        hook: Callable[[], dict] | None = getattr(app, 'harness_state', None)
        if callable(hook):
            state.update(hook())
        return state

    async def shot(self, name: str, expect: str = '') -> dict[str, Any]:
        """Record (and with ROS_TUI_SHOTS=1 write) a named screenshot; ``expect`` is for the verifier."""
        await self.idle()
        index = len(self.shots) + 1
        stem = f'{index:02d}-{re.sub(r"[^A-Za-z0-9_.-]", "-", name)}'
        console = self._render_console()
        record = {
            'name': stem,
            'expect': expect,
            'keys_since_last_shot': self.steps[self._steps_at_last_shot:],
            'keys': list(self.steps),
            'state': self.state(),
            'text': console.export_text(clear=False),
        }
        self._steps_at_last_shot = len(self.steps)
        self.shots.append(record)
        if shots_enabled():
            self._write(stem, record, console.export_svg(title=self.app.title, clear=False))
        return record

    def _render_console(self) -> Console:
        # The same rendering as textual's App.export_screenshot, kept so text and SVG come from it.
        width, height = self.app.size
        console = Console(
            width=width,
            height=height,
            file=io.StringIO(),
            force_terminal=True,
            color_system='truecolor',
            record=True,
            legacy_windows=False,
            safe_box=False,
        )
        screen = self.app.screen
        console.print(screen._compositor.render_update(full=True, screen_stack=self.app._background_screens))
        return console

    def _write(self, stem: str, record: dict[str, Any], svg: str) -> None:
        base = self.directory / stem
        base.with_suffix('.svg').write_text(svg)
        base.with_suffix('.txt').write_text(record['text'])
        meta = {key: value for key, value in record.items() if key != 'text'}
        base.with_suffix('.json').write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n')
        files = [f'{stem}.svg', f'{stem}.txt', f'{stem}.json']
        if write_png(svg, base.with_suffix('.png')):
            files.insert(0, f'{stem}.png')
        with (self.directory / 'manifest.md').open('a') as manifest:
            manifest.write(
                f'\n## {stem}\n\n'
                f'- keys since last shot: {_format_keys(record["keys_since_last_shot"])}\n'
                f'- all keys: {_format_keys(record["keys"])}\n'
                f'- expect: {record["expect"] or "—"}\n'
                f'- files: {", ".join(files)}\n'
            )


def _format_keys(keys: list[str]) -> str:
    return ' '.join(f'`{key}`' for key in keys) if keys else '(none)'


def write_png(svg: str, path: Path) -> bool:
    """Render ``svg`` to ``path`` with rsvg-convert; False (and a warning) if it is missing."""
    if shutil.which('rsvg-convert') is None:
        warnings.warn('rsvg-convert not found: shots are written as SVG/TXT/JSON only '
                      '(install librsvg2-bin, or rebuild the Docker image)')
        return False
    # Textual pads with leading spaces inside spans; keep rsvg from collapsing them. Its web
    # font (Fira Code from a CDN) is unreachable for rsvg, so name the installed design font.
    svg = svg.replace('<svg ', '<svg xml:space="preserve" ', 1)
    svg = svg.replace('font-family: Fira Code,', 'font-family: JetBrains Mono, Fira Code,')
    subprocess.run(['rsvg-convert', '-o', str(path)], input=svg.encode(), check=True)
    return True


@asynccontextmanager
async def ui_session(
    size: tuple[int, int] = DEFAULT_SIZE,
    bridge=None,
    app_factory: Callable[[Any], Any] | None = None,
    test_id: str | None = None,
):
    """Run the app headless over ``bridge`` (default ``FakeBridge.demo()``) and yield a UiSession.

    ``app_factory(bridge)`` builds the app (default ``RosTuiApp``); ``test_id`` names the artifact
    folder (default: the running pytest test's node id).
    """
    bridge = FakeBridge.demo() if bridge is None else bridge
    app = (app_factory or RosTuiApp)(bridge)
    async with app.run_test(size=size) as pilot:
        session = UiSession(app, pilot, bridge, test_id or current_test_id())
        await session.idle()
        yield session
