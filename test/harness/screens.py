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

"""Drive the app headless and take named screenshots for agents to review.

    async with ui_session() as s:                 # FakeBridge.demo(), 124x34 terminal
        await s.keys('enter', 'space')            # open /chatter, start the echo
        await s.click_on('LATEST MESSAGE')        # or click what the screen shows
        await s.advance(2.0)                      # simulated seconds (the bridge's ManualClock)
        await s.shot('echo-live', expect="/chatter echoing, data 'chatter 2'")

Every ``shot()`` records the screen text and a state summary in ``s.shots``. With
``ROS_TUI_SHOTS=1`` it also writes, into ``test/artifacts/<test id>/``:

- ``NN-name.svg``: textual's own screenshot (``App.export_screenshot``),
- ``NN-name.png``: the SVG rendered by ``rsvg-convert`` (skipped, with a warning, if missing),
- ``NN-name.txt``: the screen as plain text,
- ``NN-name.json``: the state (screen, focus, plus the nav model's
  ``NavState.summary()``), the keys pressed so far and the ``expect`` text,
- a section in ``manifest.md`` with the keys and the ``expect`` text.

See docs/agentic-dev.md.
"""

import asyncio
import io
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from harness.fake_bridge import FakeBridge
from rich.cells import cell_len
from rich.console import Console
from ros_tui.constants import UI_TICK_PERIOD_S
from textual import events
from textual.events import Click, MouseDown, MouseUp
from textual.geometry import Offset
from textual.keys import REPLACED_KEYS, _character_to_key, _get_unicode_name_from_key
from textual.pilot import _get_mouse_message_arguments
from ros_tui.ui.app import RosTuiApp

ARTIFACTS_ROOT = Path(__file__).resolve().parents[1] / 'artifacts'
SHOTS_ENV = 'ROS_TUI_SHOTS'
DEFAULT_SIZE = (124, 34)
IDLE_ROUNDS = 100  # Message rounds idle() allows before it calls the app stuck.
QUIET_ROUNDS = 3  # Rounds in a row with nothing to do that make the app idle.


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
        self._console: Console | None = None  # The last render, until the app next goes idle.
        if shots_enabled():
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory.mkdir(parents=True)
            (self.directory / 'manifest.md').write_text(f'# {test_id}\n')

    # ---------------------------------------------------------------- driving
    #
    # Pilot's press / click / pause wait for the process to go idle (textual's wait_for_idle compares
    # process CPU time with wall time) and give up only after 1 s; with ROS threads busy in the same
    # process (the end-to-end tests) every key cost seconds. The session instead waits until the
    # screen has drained its message queues, then lays out and redraws as textual's update timer
    # would: deterministic, and no real time passes.

    async def idle(self) -> None:
        """Let the app process everything queued (messages, workers), then lay out and redraw, until
        it stays quiet for QUIET_ROUNDS rounds: a key or a refresh travels between the app, the
        screen and the widgets in several hops, and a layout sends the widgets resize messages."""
        self._console = None
        quiet = 0
        for _ in range(IDLE_ROUNDS):
            await asyncio.sleep(0)
            await self.pilot._wait_for_screen()
            # A worker (importing a message type) answers with a message: drain the queues after it.
            while running := [worker for worker in self.app.workers if not worker.is_finished]:
                await self.app.workers.wait_for_complete(running)
                await self.pilot._wait_for_screen()
            screen = self.app.screen
            if any(_wants_refresh(widget) for widget in screen.walk_children()):
                quiet = 0
            elif (screen._layout_required or screen._scroll_required or screen._repaint_required
                  or screen._dirty_widgets):
                screen._on_timer_update()
                quiet = 0
            else:
                quiet += 1
                if quiet == QUIET_ROUNDS:
                    return
        raise AssertionError(f'the app did not settle in {IDLE_ROUNDS} rounds')

    async def keys(self, *keys: str) -> None:
        """Press keys one at a time (textual key names), letting the app go idle after each."""
        for key in keys:
            self.app.post_message(_key_event(self.app, key))
            self.steps.append(key)
            await self.idle()

    async def click(self, x: int, y: int) -> None:
        """Click the cell at column ``x``, row ``y`` of the screen, then let the app go idle."""
        await self._click((x, y))
        self.steps.append(f'click@{x},{y}')

    async def click_on(self, text: str, nth: int = 0, row: int | None = None) -> None:
        """Click the first cell of the ``nth`` place ``text`` shows on the screen (in screen row
        ``row`` only, if given), as a person would aim at it."""
        spots = [(cell_len(line[:at]), y) for y, line in enumerate(self.lines())
                 if row is None or y == row for at in _find_all(line, text)]
        if nth >= len(spots):
            raise AssertionError(f'{text!r} shows {len(spots)} times on the screen, wanted #{nth}')
        await self._click(spots[nth])
        self.steps.append(f'click "{text}"' + (f'#{nth}' if nth else ''))

    async def _click(self, offset: tuple[int, int]) -> None:
        # What Pilot.click sends (mouse down, up, click on the screen), without its idle waits.
        screen = self.app.screen
        arguments = _get_mouse_message_arguments(screen, offset, button=1)
        self.app.mouse_position = Offset(*offset)
        for event in (MouseDown(**arguments), MouseUp(**arguments), Click(**arguments, chain=1)):
            screen._forward_event(event)
            await self.idle()

    async def type_text(self, text: str) -> None:
        """Type ``text`` character by character (Pilot accepts single characters as keys)."""
        await self.keys(*('space' if char == ' ' else char for char in text))

    async def wait_until(self, predicate: Callable[[], Any], timeout: float = 5.0) -> bool:
        """Poll ``predicate`` in real time (for a real bridge, whose answers take real time)."""
        deadline = time.monotonic() + timeout
        await self.idle()
        while not predicate() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            await self.idle()
        return bool(predicate())

    async def advance(self, seconds: float, step: float = UI_TICK_PERIOD_S) -> None:
        """Advance the fake bridge's clock by ``seconds`` in ``step``s, ticking the app after each.

        The app's own real-time tick is paused under a ManualClock (see ``ui_session``), so its
        tick runs once per step: echo drains, toasts and spinners follow the simulated clock, and a
        1 Hz topic shows every message, the way it would in real time.
        """
        clock = getattr(self.bridge, 'clock', None)
        if clock is None:
            raise TypeError('advance() needs a bridge with a ManualClock (FakeBridge)')
        remaining = seconds
        while remaining > 1e-9:
            delta = min(step, remaining)
            clock.advance(delta)
            remaining -= delta
            self.app.tick()
            await self.idle()
        self.steps.append(f'+{seconds:g}s')

    # ---------------------------------------------------------------- looking

    def text(self) -> str:
        """The screen as plain text (what ``NN-name.txt`` holds)."""
        return self._render().export_text(clear=False)

    def lines(self) -> list[str]:
        return self.text().splitlines()

    def footer(self) -> str:
        """The bottom line: mode, breadcrumb and the key labels."""
        return self.lines()[-1]

    def line_with(self, *parts: str) -> str:
        """The first screen line holding all of ``parts`` ('' if none)."""
        return next((line for line in self.lines() if all(part in line for part in parts)), '')

    def where(self, *keys: str) -> tuple:
        """The ``state()`` values of ``keys`` (by default the layer, mode, path, area and row)."""
        state = self.state()
        return tuple(state[key] for key in keys or ('layer', 'mode', 'path', 'area', 'row'))

    def state(self) -> dict[str, Any]:
        """A JSON-able summary of where the UI is, with the nav model's own (``NavState.summary()``)."""
        app = self.app
        focused = app.focused
        state = {
            'screen': type(app.screen).__name__,
            'screen_stack': [type(screen).__name__ for screen in app.screen_stack],
            'focused': None if focused is None else {
                'id': focused.id, 'class': type(focused).__name__,
            },
        }
        state.update(app.nav.summary())
        return state

    async def shot(self, name: str, expect: str = '') -> dict[str, Any]:
        """Record (and with ROS_TUI_SHOTS=1 write) a named screenshot; ``expect`` says what a reviewer should see."""
        await self.idle()
        index = len(self.shots) + 1
        stem = f'{index:02d}-{re.sub(r"[^A-Za-z0-9_.-]", "-", name)}'
        record = {
            'name': stem,
            'expect': expect,
            'keys_since_last_shot': self.steps[self._steps_at_last_shot:],
            'keys': list(self.steps),
            'state': self.state(),
        }
        self._steps_at_last_shot = len(self.steps)
        self.shots.append(record)
        if shots_enabled():  # Rendering is the costly part: only when the shot is written.
            record['text'] = self.text()
            self._write(stem, record, self._render().export_svg(title=self.app.title, clear=False))
        return record

    def _render(self) -> Console:
        # The same rendering as textual's App.export_screenshot, kept so text and SVG come from it.
        # Kept until the app next goes idle (anything that changes the screen goes through idle()).
        if self._console is not None:
            return self._console
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
        self._console = console
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


def _wants_refresh(widget) -> bool:
    """A refresh the widget has not handed to the screen yet (textual's Widget._check_refresh)."""
    return (widget._layout_required or widget._repaint_required or widget._scroll_required
            or widget._refresh_styles_required)


def _key_event(app, key: str) -> events.Key:
    """The key event Pilot.press would send for ``key`` (a textual key name or a character)."""
    if len(key) == 1 and not key.isalnum():
        key = _character_to_key(key)
    try:
        char = unicodedata.lookup(_get_unicode_name_from_key(REPLACED_KEYS.get(key, key)))
    except KeyError:
        char = key if len(key) == 1 else None
    event = events.Key(key, char)
    event.set_sender(app)
    return event


def _find_all(line: str, text: str) -> list[int]:
    """The indices where ``text`` starts in ``line``."""
    return [at for at in range(len(line)) if line.startswith(text, at)]


def _format_keys(keys: list[str]) -> str:
    return ' '.join(f'`{key}`' for key in keys) if keys else '(none)'


def rsvg_ready(svg: str) -> str:
    """Textual's SVG screenshot made to render in rsvg-convert as it does in a browser."""
    # Textual pads with leading spaces inside spans; keep rsvg from collapsing them. Its web
    # font (Fira Code from a CDN) is unreachable for rsvg, so name the installed JetBrains Mono first.
    svg = svg.replace('<svg ', '<svg xml:space="preserve" ', 1)
    svg = svg.replace('font-family: Fira Code,', 'font-family: JetBrains Mono, Fira Code,')
    # rsvg ignores textLength, so a long run drifts unless the glyph advance (0.6 em in JetBrains
    # Mono) matches textual's 12.2 px cell: 20.333 px instead of textual's 20 px.
    return svg.replace('font-size: 20px', 'font-size: 20.333px')


def write_png(svg: str, path: Path) -> bool:
    """Render ``svg`` to ``path`` with rsvg-convert; False (and a warning) if it is missing."""
    if shutil.which('rsvg-convert') is None:
        warnings.warn('rsvg-convert not found: shots are written as SVG/TXT/JSON only '
                      '(install librsvg2-bin, or rebuild the Docker image)')
        return False
    subprocess.run(['rsvg-convert', '-o', str(path)], input=rsvg_ready(svg).encode(), check=True)
    return True


@asynccontextmanager
async def ui_session(
    size: tuple[int, int] = DEFAULT_SIZE,
    bridge=None,
    test_id: str | None = None,
):
    """Run the app headless over ``bridge`` (default ``FakeBridge.demo()``) and yield a UiSession.

    ``test_id`` names the artifact folder (default: the running pytest test's node id).
    """
    bridge = FakeBridge.demo() if bridge is None else bridge
    app = RosTuiApp(bridge)
    async with app.run_test(size=size) as pilot:
        if getattr(bridge, 'clock', None) is not None:
            app.ticker.pause()  # Simulated time: advance() ticks the app once per step.
        session = UiSession(app, pilot, bridge, test_id or current_test_id())
        await session.idle()
        yield session
