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

"""The one place log/status colour lives — semantic, theme-aware text.

Tab code never writes raw Rich style strings (``'bold red'`` etc.); it calls a builder
here and gets back a Textual ``Content`` styled with **theme variables**, so every line
follows the active theme (including ``ctrl+p → change theme``). See ``docs/STYLE_GUIDE.md``.

Two-tier colour, mirroring the theme:
  • blue  (``info``)               — interaction: requests/responses, in-flight states
  • green (``ok``) / amber (``feedback``/``warn``) / rose (``fail``) — operation outcomes

Every colour is paired with a glyph so meaning survives colour-blindness and no-colour
terminals (WCAG 1.4.1). Glyphs already embedded in message strings come from this same
vocabulary; the constants below are the source of truth for new code and the status strip.
"""

from textual.content import Content

# ── glyph vocabulary ───────────────────────────────────────────────────────────
GLYPH_REQUEST = '→'   # outbound: goal sent, service called, publish
GLYPH_RESPONSE = '←'  # inbound: service response
GLYPH_OK = '✓'        # success
GLYPH_FAIL = '✗'      # error / rejection / timeout
GLYPH_WARN = '⚠'      # warning
GLYPH_ECHO = '───'    # echo message separator
GLYPH_IDLE = '◆'      # status strip: nothing in flight
GLYPH_BUSY = '▸'      # status strip: operation in flight

# ── role → theme-variable style ──────────────────────────────────────────────────
# Keep ``info`` blue, outcomes green/amber/rose. Bold for headline lines; streaming
# (feedback) and meta (muted) stay unbolded so a wall of them does not vibrate.
_STYLE = {
    'ok': 'bold $text-success',
    'fail': 'bold $text-error',
    'info': 'bold $text-primary',
    'warn': 'bold $text-warning',
    'feedback': '$text-warning',
    'muted': '$text-muted',
    'title': 'bold $foreground',
}

# Status-strip states → (glyph, role). The single saturated "live vitals" readout.
_STATE = {
    'idle': (GLYPH_IDLE, 'muted'),
    'busy': (GLYPH_BUSY, 'info'),
    'ok': (GLYPH_OK, 'ok'),
    'fail': (GLYPH_FAIL, 'fail'),
    'warn': (GLYPH_WARN, 'warn'),
}


def styled(text: str, role: str) -> Content:
    """Plain ``text`` rendered in the named semantic ``role`` (a theme-aware Content)."""
    return Content(text).stylize(_STYLE[role])


def ok(text: str) -> Content:
    return styled(text, 'ok')


def fail(text: str) -> Content:
    return styled(text, 'fail')


def info(text: str) -> Content:
    return styled(text, 'info')


def warn(text: str) -> Content:
    return styled(text, 'warn')


def feedback(text: str) -> Content:
    return styled(text, 'feedback')


def muted(text: str) -> Content:
    return styled(text, 'muted')


def title(text: str) -> Content:
    return styled(text, 'title')


def state(label: str, role: str) -> Content:
    """A status-strip line: a leading state glyph + ``label`` in the state's colour.

    An unknown role degrades to the neutral idle look rather than crashing the UI thread.
    """
    glyph, style_role = _STATE.get(role, _STATE['idle'])
    return styled(f'{glyph} {label}', style_role)
