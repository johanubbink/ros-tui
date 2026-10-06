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

"""The field helper popup (the design's renderHelper, .hpop), right under the row it fills:

    pose.orientation  Quaternion · Quaternion helper
     x y z w   roll pitch yaw (°)   yaw only (°)   axis + angle (°)
    yaw     90.0
    = {x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}
    ────────────
    tab next way to enter it · ↑↓ field · type to change · enter applies · esc cancels

the field and its type, then an enum's options ("● 1 WARN = 1") or the strip of modes (the one on
in bright on cursor-on), what the mode does (Header, Time) and its fields (the one being typed
lit), the preview of the value, and the keys. Everything comes from `nav.helper` (helpers/).
"""

from rich.style import Style
from rich.text import Text

from ros_tui.ui.helpers import Helper
from ros_tui.ui.widgets.base import Overlay, band, cursor_bar, cursor_cell, fit, rule, style

MIN_WIDTH = 72  # The design's 560 px popup; wider when its key hint needs it.
LEFT = 5  # Cells from the body's left edge (the design's left: 44px, past the row numbers).
FIRST_ROW = 4  # Body lines above an entry panel's first row: the header, the toolbar, the border, the title.
VALUE_WIDTH = 8  # A field's value, at least (the design's min-width: 64px).


class HelperPopup(Overlay):
    DEFAULT_CSS = """
    HelperPopup { border: round $rt-key; background: $rt-pop; padding: 0 1; }
    """

    def place(self, width, height):
        helper = self.nav.helper
        if helper is None:
            return None
        natural = max(line.cell_len for line in self.body(helper, 0))
        w = min(max(MIN_WIDTH, natural + 4), width - LEFT)  # Border and padding: 4 cells across, 2 down.
        h = min(len(self.body(helper, w - 4)) + 2, height)
        room = height - FIRST_ROW - 1 - (1 if self.nav.tab and self.nav.errline(self.nav.tab) else 0)
        row = self.nav.row_index()
        line = FIRST_ROW + row - max(0, row - room + 1)  # Where the row is drawn (its panel scrolls).
        y = line + 1 if line + 1 + h <= height else max(0, line - h)
        return LEFT, y, w, h

    def lines(self, width, height):
        return self.body(self.nav.helper, width) if self.nav.helper else []

    def body(self, helper: Helper, width: int) -> list[Text]:
        lines = [Text.assemble((helper.field, style('bright', bold=True)), '  ',
                               (f'{helper.type} · {helper.name} helper', style('dim')))]
        if helper.choices:
            lines += [self.option(helper, index, width) for index in range(len(helper.choices))]
        else:
            lines.append(Text(' ').join(Text(f' {mode.name} ', style('bright', 'cursor-on', bold=True)
                                             if index == helper.mode else style('grey'))
                                        for index, mode in enumerate(helper.modes())))
            if helper.note():
                lines.append(Text(helper.note(), style('dim')))
            fields = helper.fields()
            lines.append(Text('  ').join(self.field(helper, name, index == helper.cur) for index, name in
                                         enumerate(fields)) if fields else Text('nothing to fill in', style('dim')))
        result = helper.result()
        lines.append(Text(f'= {result.label}', style('ok')) if result else Text('= fix the values first', style('bad')))
        return lines + [rule(width), Text(helper.keys(), style('help-field'))]

    @staticmethod
    def option(helper: Helper, index: int, width: int) -> Text:
        """An enum's option: "● 1 WARN = 1", the picked one on a band."""
        name, number = helper.choices[index]
        on = index == helper.cur
        line = Text.assemble(cursor_bar(on), ('● ' if on else '○ ', style('bright' if on else 'grey')),
                             (str(index), style('key', bold=True)), ' ', (name, style('bright' if on else 'text')),
                             ' ', (f'= {number}', style('dim')))
        return band(line, width, 'cursor-on') if on else line

    @staticmethod
    def field(helper: Helper, name: str, on: bool) -> Text:
        """A field to type: its name, then its value underlined, lit with the text cursor when on."""
        look = style('bright', 'hb-on' if on else '') + Style(underline=True)
        value = Text(helper.values[name].rjust(VALUE_WIDTH), look)
        if on:
            value.append_text(cursor_cell())
        return Text.assemble((name, style('grey')), ' ', fit(value, max(VALUE_WIDTH, value.cell_len)))
