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

"""The tab row (the design's renderTabRow and fitTabs): ☰ plus one tab per open entry.

Two lines: the tabs, and under them a rule that underlines the active tab in its kind's colour.
On the tab-row layer the cursor tab is outlined in the key colour. When the tabs don't fit, the
row scrolls by whole tabs to keep the active (or cursor) tab in view and says how many are hidden
on each side ("‹ 2 more", "3 more ›").
"""

from rich.text import Text

from ros_tui.ui.nav import KINDS as NAV_KINDS, TABS
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.base import NavView, fit, style

MARKER_WIDTH = 10  # Room kept for "‹ 12 more" / "12 more ›" at an edge that hides tabs.
UNDERLINE = '▔'  # The rule under the tabs; the active tab's part is in its kind's colour.


def fit_tabs(widths: list[int], want: int, start: int, room: int) -> tuple[int, int]:
    """The tabs [first, end) to show in `room` cells: as few changes from `start` (the first tab
    shown last time) as keep tab `want` visible, leaving MARKER_WIDTH at each edge that hides tabs."""

    def end_from(first: int) -> int:
        space = room - (MARKER_WIDTH if first > 0 else 0)
        end, used = first, 0
        while end < len(widths) and used + widths[end] <= space:
            used += widths[end]
            end += 1
        while end < len(widths) and end > first + 1 and used > space - MARKER_WIDTH:
            end -= 1
            used -= widths[end]
        return max(end, first + 1)

    first = max(0, min(start, want, len(widths) - 1))
    while want >= end_from(first) and first < want:
        first += 1
    # Use spare room on the right by showing more tabs on the left.
    while first > 0 and end_from(first - 1) >= end_from(first) and want < end_from(first - 1):
        first -= 1
    return first, end_from(first)


class EntryTabRow(NavView):
    DEFAULT_CSS = """
    EntryTabRow { height: 2; background: $rt-strip; padding: 0 1; }
    """

    def __init__(self, nav, **kwargs):
        super().__init__(nav, **kwargs)
        self._first = 0  # The first tab shown (0 is ☰), kept between renders like the design's scroll.

    def segments(self) -> list[tuple[Text, str]]:
        """Every tab (☰ first) as (its text, its underline colour: its kind's when active, else '')."""
        nav = self.nav
        cursor = nav.tab_cur if nav.layer == TABS else None
        label = 'All' if nav.chip < 0 else KINDS[NAV_KINDS[nav.chip]].label
        home = [('0 ', 'number'), (f'☰ {label}', '')]
        segments = [_segment(home, nav.active < 0, cursor == -1, 'label', 'accent-fill')]
        for index, tab in enumerate(nav.tabs):
            kind = KINDS[tab.kind]
            parts = [(f'{index + 1} ', 'number')] if index < 9 else []
            parts += [(kind.glyph + ' ', kind.color), (tab.name, ''), (' ×', 'dim')]
            segments.append(_segment(parts, index == nav.active, cursor == index, 'grey', kind.color))
        return segments

    def lines(self, width, height):
        nav = self.nav
        segments = self.segments()
        want = (nav.tab_cur if nav.layer == TABS else nav.active) + 1
        first, end = fit_tabs([text.cell_len for text, _ in segments], want, self._first, width)
        self._first = first
        top, rule = Text(), Text()
        if first:
            top.append_text(fit(Text(f'‹ {first} more', style('key')), MARKER_WIDTH))
            rule.append(UNDERLINE * MARKER_WIDTH, style('rule'))
        for text, underline in segments[first:end]:
            top.append_text(text)
            rule.append(UNDERLINE * text.cell_len, style(underline or 'rule'))
        if end < len(segments):
            marker = Text(f'{len(segments) - end} more ›', style('key'))
            top = fit(top, width - marker.cell_len) + marker
        return [top, fit(rule + Text(UNDERLINE * width, style('rule')), width)]


def _segment(parts: list[tuple[str, str]], active: bool, cursor: bool, rest: str, kind_color: str):
    """One tab: `parts` are (text, colour) pairs, '' taking the tab's own colour (grey at rest,
    white when active, the key colour under the tab-row cursor, which also outlines it)."""
    bg = 'tab-cur' if cursor else 'tab-on' if active else ''
    own = style('key' if cursor else 'bright' if active else rest, bg, bold=active or cursor)
    edge = style('key', bg) if cursor else own
    text = Text.assemble(('▏' if cursor else ' ', edge),
                         *((part, style(color, bg) if color else own) for part, color in parts),
                         ('▕' if cursor else ' ', edge))
    return text, kind_color if active else ''
