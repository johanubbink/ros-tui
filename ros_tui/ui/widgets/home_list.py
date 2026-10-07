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

The chips are pills (`base.switch`), the one that is on in blue; a click on one filters the list.
The table's columns share the width as the design's auto-sized table does: each gets its widest
cell plus padding, and the room left over in proportion. Each kind's group starts after a blank
line. The cursor row is highlighted; while the list has the keys (layer `in`) it is brighter and
marked with a bar in the key colour. A click on a row opens it. The rows scroll to keep the cursor
in view.
"""

from rich.cells import cell_len
from rich.text import Text

from ros_tui.ui.nav import IN, KINDS as NAV_KINDS
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.base import NavView, clickable, cursor_bar, fit, glyph, markers, style, switch

COLUMN_PAD = 3  # Cells after each column's widest cell (the design's td padding).
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
            count = len(nav.catalog[kind]) if kind else sum(len(items) for items in nav.catalog.values())
            label = Text.assemble(glyph(kind) if kind else '', KINDS[kind].label if kind else 'All',
                                  (f' {count}', style('grey' if on else 'dim')))
            line.append_text(clickable(switch((label, on, None)), ('chip', index)))
            line.append(' ')
        return fit(line, width)

    def cells(self) -> list[tuple[str, object, Text]]:
        """The rows as (kind, item, its Here cell: what runs, and "open")."""
        nav = self.nav
        cells = []
        for kind, item in nav.home_rows():
            here = markers(nav.running(kind, item.name), labels=True)
            if nav.is_open(kind, item.name):
                here.append((' ' if here else '') + 'open', style('dim'))
            cells.append((kind, item, here))
        return cells

    def columns(self, width: int, cells: list[tuple[str, object, Text]]) -> tuple[int, int, int]:
        """The widths of the Name, Type and Here columns, as the design's table lays them out."""
        name = 3 + max([2] + [cell_len(item.name) for _, item, _ in cells]) + COLUMN_PAD  # 3: the bar and the glyph.
        kind = max([4] + [cell_len(item.type) for _, item, _ in cells]) + COLUMN_PAD
        here = max([4] + [here.cell_len for _, _, here in cells]) + COLUMN_PAD
        total = name + kind + here
        if total > width:  # The Type column gives way.
            return name, max(0, width - name - here), here
        name, here = name * width // total, here * width // total
        return name, width - name - here, here

    def rows(self, cells: list[tuple[str, object, Text]], widths: tuple[int, int, int]) -> tuple[list[Text], int, int]:
        """The table rows, group headers (each after a blank line) included, and the span [first,
        last] of lines to keep in view: the cursor's row, and its group header when it's the group's
        first entry."""
        nav = self.nav
        name_w, type_w, here_w = widths
        on = nav.layer == IN and nav.tab is None
        lines, keep, last = [], (0, 0), None
        for index, (kind, item, here) in enumerate(cells):
            first = kind != last
            if first:
                count = f'{kind.upper()} · {len(nav.catalog[kind])}'
                lines += [Text(), Text.assemble(' ', glyph(kind), (count, style('head')))]
                last = kind
            sel = index == nav.list_cur
            if sel:
                keep = (len(lines) - (1 if first else 0), len(lines))
            line = Text.assemble(
                cursor_bar(sel and on), glyph(kind),
                fit(Text(item.name, style('bright') if sel else ''), name_w - 3),
                fit(Text(item.type, style('bright' if sel else 'type')), type_w),
                fit(here, here_w))
            if sel:
                line.stylize(style(bg='cursor-on' if on else 'cursor'))
            lines.append(clickable(line, ('open', (kind, item.name))))
        return lines, *keep

    def lines(self, width, height):
        cells = self.cells()
        if not cells:
            return [self.chips(width), Text(), Text('  nothing here yet — waiting for the ROS graph', style('dim'))]
        widths = self.columns(width, cells)
        rows, keep_first, keep_last = self.rows(cells, widths)
        name_w, type_w, _ = widths
        header = Text.assemble('   Name'.ljust(name_w), 'Type'.ljust(type_w), 'Here', style=style('head'))
        room = max(1, height - TOP_LINES)
        self._top = max(min(self._top, keep_first), keep_last - room + 1)
        self._top = max(0, min(self._top, len(rows) - room))
        return [self.chips(width), Text(), header] + rows[self._top:self._top + room]
