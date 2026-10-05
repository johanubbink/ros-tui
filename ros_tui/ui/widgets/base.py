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

"""What every widget of the new UI shares: `NavView` (render the NavState as lines) and text helpers."""

from rich.style import Style
from rich.text import Text
from textual.widget import Widget

from ros_tui.ui.nav import NavState
from ros_tui.ui.theme import KINDS, TOKENS


class NavView(Widget):
    """A widget that draws part of a NavState. It never takes focus and has no bindings: the app
    hands every key to the NavState and then refreshes the views (NextApp.refresh_views)."""

    can_focus = False

    def __init__(self, nav: NavState, **kwargs):
        super().__init__(**kwargs)
        self.nav = nav

    def lines(self, width: int, height: int) -> list[Text]:
        raise NotImplementedError

    def render(self) -> Text:
        width, height = self.size
        text = Text('\n').join(fit(line, width) for line in self.lines(width, height))
        text.no_wrap = True
        text.overflow = 'crop'
        return text


def style(color: str = '', bg: str = '', bold: bool = False) -> Style:
    """A Style from theme token names or hex values: style('key', bold=True)."""
    return Style(color=TOKENS.get(color, color) or None, bgcolor=TOKENS.get(bg, bg) or None, bold=bold)


def fit(line: Text, width: int, bg: str = '') -> Text:
    """`line` cropped or padded with spaces to exactly `width` cells (the padding on `bg`)."""
    line = line.copy()
    line.truncate(width, overflow='crop', pad=False)
    if line.cell_len < width:
        line.append(' ' * (width - line.cell_len), style(bg=bg) if bg else '')
    return line


def spread(left: Text, right: Text, width: int, bg: str = '') -> Text:
    """`left`, then `right` pushed to the right edge; the left part is cropped if they don't fit."""
    room = max(0, width - right.cell_len)
    line = fit(left, room, bg) if left.cell_len < room else fit(left, max(0, room - 1), bg) + Text(' ')
    return fit(line + right, width, bg)


def glyph(kind: str) -> Text:
    """The kind's glyph in its tint, with the space after it ("≋ ")."""
    return Text(KINDS[kind].glyph + ' ', style(KINDS[kind].color))


def keyed(key: str, label: str, label_color: str = 'grey') -> Text:
    """A key in the key colour followed by what it does: "esc tab row"."""
    return Text.assemble((key, style('key', bold=True)), (' ' + label if label else '', style(label_color)))
