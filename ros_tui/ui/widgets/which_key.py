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

"""The which-key popups (the design's renderWk): `?` lists the keys right now, `g` what can follow it.

Bottom right, above the footer. Both come from the keymap (`keymap.which_key_items`): a title,
then each group's heading and its keys in two columns (a key whose label is too long takes a line).
"""

from rich.text import Text

from ros_tui.ui import keymap
from ros_tui.ui.widgets.base import Overlay, fit, style

WIDTH = 82  # The design's 640 px popup.
G_WIDTH = 48  # The narrow g… popup (380 px).
KEY_WIDTH = 5  # The key column of a cell (min-width: 40px).
GAP = 2  # Between the two columns.
TITLES = {'all': 'Keys right now · any key closes', 'g': 'g …  waiting for the next key'}


class WhichKeyPopup(Overlay):
    DEFAULT_CSS = """
    WhichKeyPopup { border: round $rt-pop-edge; background: $rt-pop-2; padding: 0 1; }
    """

    def place(self, width, height):
        if not self.nav.which_key:
            return None
        w = min(G_WIDTH if self.nav.which_key == 'g' else WIDTH, width - 2)
        h = min(len(self.body(w - 4)) + 2, height - 1)  # Border and padding: 4 cells across, 2 down.
        return width - w - 1, height - 1 - h, w, h

    def lines(self, width, height):
        return self.body(width)

    def body(self, width: int) -> list[Text]:
        col = (width - GAP) // 2
        lines = [Text(TITLES[self.nav.which_key], style('pop-title')), Text()]
        rows = keymap.which_key_items(self.nav)
        for group in dict.fromkeys(row.group for row in rows):
            lines.append(Text(group.upper(), style('feed-head')))
            lines += self.pairs([self.cell(row) for row in rows if row.group == group], col, width)
        return lines

    @staticmethod
    def pairs(cells: list[Text], col: int, width: int) -> list[Text]:
        """Two cells to a line, in order; a cell too long for a column gets a line of its own."""
        lines, left = [], None
        for cell in cells:
            if cell.cell_len > col:
                lines += ([fit(left, col)] if left else []) + [fit(cell, width)]
                left = None
            elif left is None:
                left = cell
            else:
                lines.append(Text(' ' * GAP).join([fit(left, col), fit(cell, col)]))
                left = None
        return lines + ([fit(left, col)] if left else [])

    @staticmethod
    def cell(row: keymap.KeyRow) -> Text:
        key = Text(row.keys, style('key', bold=True))
        return Text.assemble(fit(key, max(KEY_WIDTH, key.cell_len) + 1), (row.label, style('text')))
