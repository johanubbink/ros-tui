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

"""The ☰ list: kind chips, then every entry grouped by kind.

The chips are pills (`base.switch`), the one that is on in blue; a click on one filters the list.
The table's columns share the width: each gets its widest
cell plus padding, and the room left over in proportion. Each kind's group starts after a blank
line. The cursor row is highlighted; while the list has the keys (layer `in`) it is brighter and
marked with a bar in the key colour. A click on a row opens it. The rows scroll to keep the cursor
in view.
"""

from rich.text import Text

from ros_tui.ui.nav import IN, KINDS as NAV_KINDS, Tab
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.base import (NavView, clickable, column_width, cursor_bar, fit, glyph, here, scroll_top, style,
                                     switch)

COLUMN_PAD = 3  # Cells after each column's widest cell.
TOP_LINES = 3  # Lines above the rows: the chips, a blank line and the column header.


class HomeList(NavView):
    DEFAULT_CSS = """
    HomeList { height: 1fr; }
    """

    def __init__(self, nav, **kwargs):
        super().__init__(nav, **kwargs)
        self._top = 0  # The first list row shown, kept between renders.

    def chips(self, width: int) -> Text:
        """"tab: All 12  ≋ Topics 6 …", the chip that filters the list on."""
        nav = self.nav
        line = Text.assemble(('tab: ', style('dim')))
        for index in range(-1, len(NAV_KINDS)):
            kind = NAV_KINDS[index] if index >= 0 else None
            on = nav.chip == index
            count = len(nav.catalog[kind]) if kind else len(nav.catalog)
            label = Text.assemble(glyph(kind) if kind else '', KINDS[kind].label if kind else 'All',
                                  (f' {count}', style('grey' if on else 'dim')))
            line.append_text(clickable(switch((label, on, None)), ('chip', index)))
            line.append(' ')
        return fit(line, width)

    def cells(self) -> list[tuple[str, object, Text]]:
        """The rows as (kind, item, its Here cell: what runs, and "open"). Only an entry that was
        opened has anything to say there."""
        nav = self.nav
        known = {*nav.entries, *nav.tabs}
        return [(kind, item, here(nav, kind, item.name, 'open') if Tab(kind, item.name) in known else Text())
                for kind, item in nav.catalog.rows(nav.chip)]

    def columns(self, width: int, cells: list[tuple[str, object, Text]]) -> tuple[int, int, int]:
        """The widths of the Name, Type and Here columns."""
        name = 3 + column_width((item.name for _, item, _ in cells), 2 + COLUMN_PAD, COLUMN_PAD)  # 3: the bar, the glyph.
        kind = column_width((item.type for _, item, _ in cells), 4 + COLUMN_PAD, COLUMN_PAD)
        here_w = column_width((cell.plain for _, _, cell in cells), 4 + COLUMN_PAD, COLUMN_PAD)
        total = name + kind + here_w
        if total > width:  # The Type column gives way.
            return name, max(0, width - name - here_w), here_w
        name, here_w = name * width // total, here_w * width // total
        return name, width - name - here_w, here_w

    def layout(self, cells: list[tuple[str, object, Text]]) -> tuple[list[int | str | None], int, int]:
        """The table's lines, each a row (its index in `cells`), a group header (its kind) or a
        blank line (None) before each header, and the span [first, last] of lines to keep in view:
        the cursor's row, and its group header when it's the group's first entry."""
        lines, keep, last = [], (0, 0), None
        for index, (kind, _, _) in enumerate(cells):
            first = kind != last
            if first:
                lines += [None, kind]
                last = kind
            if index == self.nav.list_cur:
                keep = (len(lines) - (1 if first else 0), len(lines))
            lines.append(index)
        return lines, *keep

    def line(self, at: int | str | None, cells: list[tuple[str, object, Text]], widths: tuple[int, int, int]) -> Text:
        """One line of the table (see `layout`); only the lines in view are made."""
        nav = self.nav
        if at is None:
            return Text()
        if isinstance(at, str):
            return Text.assemble(' ', glyph(at), (f'{at.upper()} · {len(nav.catalog[at])}', style('head')))
        name_w, type_w, here_w = widths
        kind, item, here_cell = cells[at]
        on = nav.layer == IN and nav.tab is None
        sel = at == nav.list_cur
        line = Text.assemble(
            cursor_bar(sel and on), glyph(kind),
            fit(Text(item.name, style('bright') if sel else ''), name_w - 3),
            fit(Text(item.type, style('bright' if sel else 'type')), type_w),
            fit(here_cell, here_w))
        if sel:
            line.stylize(style(bg='cursor-on' if on else 'cursor'))
        return clickable(line, ('open', (kind, item.name)))

    def lines(self, width, height):
        cells = self.cells()
        if not cells:
            return [self.chips(width), Text(), Text('  nothing here yet — waiting for the ROS graph', style('dim'))]
        widths = self.columns(width, cells)
        layout, keep_first, keep_last = self.layout(cells)
        name_w, type_w, _ = widths
        header = Text.assemble('   Name'.ljust(name_w), 'Type'.ljust(type_w), 'Here', style=style('head'))
        room = max(1, height - TOP_LINES)
        self._top = scroll_top(self._top, keep_first, keep_last, room, len(layout))
        return [self.chips(width), Text(), header] + [self.line(at, cells, widths)
                                                      for at in layout[self._top:self._top + room]]
