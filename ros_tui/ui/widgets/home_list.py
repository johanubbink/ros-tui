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

"""The ☰ list (the design's renderHome): kind chips, then every entry grouped by kind.

The cursor row is highlighted; while the list has the keys (layer `in`) it is brighter and marked
with a bar in the key colour. The rows scroll to keep the cursor in view.
"""

from rich.text import Text

from ros_tui.ui.nav import IN, KINDS as NAV_KINDS
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.base import NavView, cursor_bar, fit, glyph, markers, spread, style

HERE_WIDTH = 26  # The Here column: '◉ echoing ↻ 10 Hz open'.
NAME_SHARE = 0.3  # The Name column's share of the width, when the names are shorter.


class HomeList(NavView):
    DEFAULT_CSS = """
    HomeList { height: 1fr; }
    """

    def __init__(self, nav, **kwargs):
        super().__init__(nav, **kwargs)
        self._top = 0  # The first list row shown, kept between renders.

    def chips(self, width: int) -> Text:
        """"tab: All 12 · ≋ Topics 6 …", the chip that filters the list on."""
        nav = self.nav
        line = Text.assemble(('tab: ', style('dim')))
        for chip in range(-1, len(NAV_KINDS)):
            kind = NAV_KINDS[chip] if chip >= 0 else None
            on = nav.chip == chip
            count = len(nav.catalog[kind]) if kind else sum(len(items) for items in nav.catalog.values())
            text = Text.assemble(' ', glyph(kind) if kind else '',
                                 (KINDS[kind].label if kind else 'All', style('bright' if on else 'grey', bold=on)),
                                 (f' {count} ', style('grey' if on else 'dim')))
            text.stylize(style(bg='cursor' if on else 'term-3'))
            line.append_text(text)
            line.append(' ')
        return spread(line, Text('/ to search · enter opens · : for commands', style('dim')), width)

    def columns(self, width: int) -> tuple[int, int]:
        """The widths of the Name and Type columns; Here gets HERE_WIDTH."""
        longest = max((len(item.name) for _, item in self.nav.home_rows()), default=0)
        name_w = max(int(width * NAME_SHARE), longest + 6)
        return name_w, max(0, width - name_w - HERE_WIDTH)

    def rows(self, width: int) -> tuple[list[Text], int, int]:
        """The table rows, group headers included, and the span [first, last] of lines to keep in
        view: the cursor's row, and its group header when it's the group's first entry."""
        nav = self.nav
        name_w, type_w = self.columns(width)
        on = nav.layer == IN and nav.tab is None
        bg = 'cursor-on' if on else 'cursor'
        lines, keep, last = [], (0, 0), None
        for index, (kind, item) in enumerate(nav.home_rows()):
            first = kind != last
            if first:
                count = f'{kind.upper()} · {len(nav.catalog[kind])}'
                lines.append(Text.assemble(' ', glyph(kind), (count, style('head'))))
                last = kind
            sel = index == nav.list_cur
            if sel:
                keep = (len(lines) - (1 if first else 0), len(lines))
            here = markers(nav.running(kind, item.name), labels=True)
            if nav.is_open(kind, item.name):
                here.append((' ' if here else '') + 'open', style('dim'))
            line = Text.assemble(
                cursor_bar(sel and on), glyph(kind),
                fit(Text(item.name, style('bright') if sel else ''), name_w - 3),
                fit(Text(item.type, style('bright' if sel else 'type')), type_w),
                fit(here, HERE_WIDTH))
            if sel:
                line.stylize(style(bg=bg))
            lines.append(line)
        return lines, *keep

    def lines(self, width, height):
        rows, keep_first, keep_last = self.rows(width)
        if not rows:
            return [self.chips(width), Text(), Text('  nothing here yet — waiting for the ROS graph', style('dim'))]
        name_w, type_w = self.columns(width)
        header = Text.assemble('   Name'.ljust(name_w), 'Type'.ljust(type_w), 'Here', style=style('head'))
        room = max(1, height - 2)
        self._top = max(min(self._top, keep_first), keep_last - room + 1)
        self._top = max(0, min(self._top, len(rows) - room))
        return [self.chips(width), header] + rows[self._top:self._top + room]
