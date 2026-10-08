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

"""The search popup: `/` or ^f, over a veil, everything by name or type.

An input line with the count, then the matches grouped by kind (the match highlighted in the name,
the short type, "open tab" for entries already open) and a hint line. At most MAX_ROWS matches show;
the window scrolls to keep the picked one in view. A click on a match opens it.
"""

from rich.text import Text

from ros_tui.ui.fields import short_type
from ros_tui.ui.nav import Search
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.base import (BODY_TOP, Overlay, band, clickable, cursor_bar, cursor_cell, glyph, here, rule,
                                     scroll_top, spread, style)

WIDTH = 84  # Cells.
MAX_ROWS = 13  # Matches shown at once.
PLACEHOLDER = 'any topic, service, action or node'
NO_MATCHES = 'no matches — backspace to change the search'
HINT = '↑↓ picks · enter opens in a tab · esc closes'


def _short_type(kind: str, type_name: str) -> str:
    """The type as a match shows it: 'String' for std_msgs/msg/String, 'node' for a node."""
    return 'node' if kind == 'nodes' else short_type(type_name)


def highlight(name: str, query: str) -> Text:
    """`name` with the first match of `query` (any case) in the key colour."""
    at = name.lower().find(query.lower()) if query else -1
    if at < 0:
        return Text(name)
    return Text.assemble(name[:at], (name[at:at + len(query)], style('key', bold=True)), name[at + len(query):])


class SearchPopup(Overlay):
    DEFAULT_CSS = """
    SearchPopup { border: round $rt-key; background: $rt-pop; }
    """

    def __init__(self, nav, **kwargs):
        super().__init__(nav, **kwargs)
        self._top = 0  # The first match shown, kept between renders.

    def place(self, width, height):
        if not self.nav.shown(Search):
            return None
        w = min(WIDTH, width - 4)
        h = min(len(self.body(w - 2)) + 2, height - BODY_TOP - 1)  # The border takes 2 cells each way.
        return (width - w) // 2, BODY_TOP, w, h

    def lines(self, width, height):
        return self.body(width)

    def body(self, width: int) -> list[Text]:
        nav = self.nav
        query = nav.overlay.q
        rows = nav.catalog.search(query)
        typed = Text.assemble(' ', ('/', style('key', bold=True)), ' ', (query, style('bright')), cursor_cell())
        if not query:
            typed.append(' ' + PLACEHOLDER, style('dim'))
        lines = [spread(typed, Text(f'{len(rows)} ', style('dim')), width), rule(width)]
        if not rows:
            lines.append(Text(' ' + NO_MATCHES, style('dim')))
        cur = nav.overlay.cur
        self._top = scroll_top(self._top, cur, cur, MAX_ROWS, len(rows))
        last = None
        for index in range(self._top, min(len(rows), self._top + MAX_ROWS)):
            kind, item = rows[index]
            if kind != last:
                lines.append(Text.assemble(' ', glyph(kind), (KINDS[kind].label.upper(), style('dim'))))
                last = kind
            lines.append(self.row(kind, item, query, index == cur, width))
        return lines + [rule(width), Text(' ' + HINT, style('head'))]

    def row(self, kind: str, item, query: str, sel: bool, width: int) -> Text:
        left = Text.assemble(cursor_bar(sel), glyph(kind), highlight(item.name, query),
                             '  ', (_short_type(kind, item.type), style('type')))
        right = here(self.nav, kind, item.name, 'open tab')
        if right:
            right.append(' ')
        line = spread(left, right, width)
        line.stylize_before(style('bright' if sel else 'text'))
        return clickable(band(line, width, 'cursor-on') if sel else line, ('open', (kind, item.name)))
