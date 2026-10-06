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

from ros_tui.ui.nav import NavState, Running
from ros_tui.ui.theme import KINDS, TOKENS

BODY_TOP = 3  # Screen rows above the body: the top bar and the two-line tab row.


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


class Overlay(NavView):
    """A NavView drawn on top of the others: on the `overlay` layer, placed absolutely in its
    parent. After each key the app asks `place` where it goes (NextApp.refresh_views)."""

    DEFAULT_CSS = """
    Overlay { layer: overlay; position: absolute; }
    """

    def place(self, width: int, height: int) -> tuple[int, int, int, int] | None:
        """(x, y, width, height) in a parent of `width` x `height` cells, or None to hide it."""
        raise NotImplementedError


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


def band(line: Text, width: int, bg: str) -> Text:
    """`line` fitted to `width` on the background `bg` (a cursor row, the picked suggestion)."""
    line = fit(line, width)
    line.stylize(style(bg=bg))
    return line


def spread(left: Text, right: Text, width: int, bg: str = '') -> Text:
    """`left`, then `right` pushed to the right edge; the left part is cropped if they don't fit."""
    room = max(0, width - right.cell_len)
    line = fit(left, room, bg) if left.cell_len < room else fit(left, max(0, room - 1), bg) + Text(' ')
    return fit(line + right, width, bg)


def glyph(kind: str) -> Text:
    """The kind's glyph in its tint, with the space after it ("≋ ")."""
    return Text(KINDS[kind].glyph + ' ', style(KINDS[kind].color))


def markers(running: tuple[Running, ...], labels: bool = False) -> Text:
    """What an entry has running, in each marker's tone: " ◉ ↻" after a tab's name, or with
    `labels` "◉ echoing ↻ 10 Hz" (the Here column, search rows)."""
    if labels:
        return Text(' ').join(Text(f'{m.glyph} {m.label}', style(m.tone)) for m in running)
    return Text.assemble(*((' ' + m.glyph, style(m.tone)) for m in running))


def cursor_bar(on: bool) -> Text:
    """The first cell of a row: the cursor's `▍` bar in the key colour when `on`, else a space."""
    return Text('▍' if on else ' ', style('key'))


def rule(width: int) -> Text:
    """A rule across a popup (the design's 1px border-bottom of a popup's header)."""
    return Text('─' * width, style('pop-line'))


def cursor_cell() -> Text:
    """The text cursor at the end of a typed value (the design's .cur block)."""
    return Text(' ', style('term', 'text'))


def keyed(key: str, label: str, label_color: str = 'grey') -> Text:
    """A key in the key colour followed by what it does: "esc tab row"."""
    return Text.assemble((key, style('key', bold=True)), (' ' + label if label else '', style(label_color)))


def edit_value(value: str, fresh: bool = False) -> Text:
    """A value being typed (the design's .edit, or .edit.fresh when the first key replaces it), with
    the text cursor at its end. The value is underlined, standing in for the design's outline."""
    return Text.assemble((value, style('bright', 'edit-fresh' if fresh else 'edit') + Style(underline=True)),
                         cursor_cell())


BUTTON_LOOKS = {  # The design's .btn looks -> (text colour, background, its key's colour).
    '': ('btn-text', 'btn', 'key'),
    'pri': ('bright', 'accent-fill', 'key'),
    'stop': ('warn', 'stop-bg', 'warn'),
}


def button(label: Text | str, key: str, look: str = '') -> Text:
    """A button with its key, as the design's `<button class="btn pri">▶ Call<span class="k">space`:
    the label (a Text may style parts of itself) and the key on the look's background."""
    color, bg, key_color = BUTTON_LOOKS[look]
    text = Text.assemble(' ', label, ' ')
    text.stylize_before(style(color, bg, bold=look != ''))
    text.append(f'{key} ', style(key_color, bg))
    return text
