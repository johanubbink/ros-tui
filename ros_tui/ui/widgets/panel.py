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

"""The panels (areas) of an entry, as the design's .panel / .pt / .pb / .l.sel / .errline.

An entry's renderer describes each area as a `Panel`: its body lines, which line is the current
row, the hints after the title and an errline. `draw_panel` draws it in one of three states:

- at rest (''): a `tline` border,
- selected ('sel', the area picked on the IN layer): a `key` border, the title on `tab-cur`; in an
  area whose rows `i` edits from there (`Panel.edits`), the row it would edit has a dim `▍`,
- inside ('in', the AREA and EDIT layers): an `accent-fill` border, the title on `panel-in`, and
  the current row on `row-in` with a `▍` bar in `accent-fill`.

`panel_state` says which one an area is in; `split` and `side_by_side` lay panels out in columns.
"""

from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.text import Text

from ros_tui.ui.nav import AREA, EDIT, IN, NavState
from ros_tui.ui.widgets.base import fit, spread, style

PANEL_TOP = 2  # Lines above a panel's body: the border and the title bar.
PANEL_LOOKS = {  # panel state -> (border colour, title background)
    '': ('tline', 'term-3'),
    'sel': ('key', 'tab-cur'),
    'in': ('accent-fill', 'panel-in'),
}


@dataclass
class Panel:
    title: str  # In capitals, as the Area's.
    lines: list[Text] = field(default_factory=list)  # The body, one Text per line.
    hint: Text = field(default_factory=Text)  # After the title, e.g. "enter edits · space sets".
    aside: Text = field(default_factory=Text)  # At the right of the title bar, e.g. "3 received · 1.0 Hz".
    cursor: int | None = None  # The line of the current row; None when the area has no rows.
    errline: str = ''  # Shown under the body, after "✗ ".
    wrap: bool = False  # Wrap long lines (the design's .lwrap) instead of cropping them.
    edits: bool = False  # i edits its current row from the area pick, so the row is marked while selected.


def panel_state(nav: NavState, index: int) -> str:
    """'sel', 'in' or '' for the entry's area at `index`, as the design's pcls()."""
    if index != nav.area_index() or nav.editing and nav.editing.area == 'rate' and nav.layer == EDIT:
        return ''
    return {IN: 'sel', AREA: 'in', EDIT: 'in'}.get(nav.layer, '')


def draw_panel(panel: Panel, width: int, height: int, state: str = '') -> list[Text]:
    """`panel` as `height` lines of `width` cells: border, title bar, body (scrolled to keep the
    current row in view) and the errline."""
    border, title_bg = PANEL_LOOKS[state]
    edge = style(border)
    inner = max(0, width - 2)
    title = Text(' ', style('panel-hint', title_bg))
    title.append(panel.title, style('label', bold=True))
    if panel.hint:
        title.append('  ')
        title.append_text(panel.hint)
    if panel.aside:
        title = spread(title, panel.aside + Text(' '), inner)
    lines, current, top, room = _scrolled(panel, inner, height)
    look = 'in' if state == 'in' else 'mark' if state == 'sel' and panel.edits else ''
    body = [_row(lines[i] if i < len(lines) else Text(), inner, look if i in current else '')
            for i in range(top, top + room)]
    if panel.errline:
        body.append(fit(Text(' ✗ ' + panel.errline, style('bad', 'err-bg')), inner))
    framed = [Text.assemble(('│', edge), line, ('│', edge)) for line in [fit(title, inner)] + body]
    return [Text('╭' + '─' * inner + '╮', edge)] + framed + [Text('╰' + '─' * inner + '╯', edge)]


def cursor_line(panel: Panel, width: int, height: int) -> int | None:
    """The line of `draw_panel(panel, width, height)` that the current row ends on (the line under
    it is where a popup for the row goes), or None when the panel has no current row."""
    _, current, top, _ = _scrolled(panel, max(0, width - 2), height)
    return PANEL_TOP + current[-1] - top if current else None


def _scrolled(panel: Panel, inner: int, height: int) -> tuple[list[Text], list[int], int, int]:
    """The body lines (wrapped if the panel wraps), the indices of the current row's lines, the first
    line shown (scrolled to keep the current row in view) and how many lines are shown."""
    room = max(0, height - PANEL_TOP - 1 - (1 if panel.errline else 0))
    lines, owners = panel.lines, list(range(len(panel.lines)))
    if panel.wrap:
        pieces = [(piece, index) for index, line in enumerate(panel.lines) for piece in wrapped(line, inner - 1)]
        lines, owners = [piece for piece, _ in pieces], [index for _, index in pieces]
    current = [i for i, owner in enumerate(owners) if owner == panel.cursor]
    top = max(0, current[-1] - room + 1) if current else 0
    return lines, current, top, room


def _row(content: Text, width: int, look: str = '') -> Text:
    """One body line on the panel background; the current row inside the area ('in') is a band with
    the bar in `accent-fill`, and the row `i` would edit from the area pick ('mark') has the bar in
    `row-mark`, without the band."""
    row = Text(style=style(bg='row-in' if look == 'in' else 'term-2'))
    row.append('▍' if look else ' ', style('accent-fill' if look == 'in' else 'row-mark'))
    row.append_text(content)
    return fit(row, width)


def wrapped(line: Text, width: int, indent: int = 2) -> list[Text]:
    """`line` cut into pieces of at most `width` cells, at a space where there is one; the pieces
    after the first are indented by `indent`."""
    pieces = []
    while line.cell_len > width > indent:
        fits = _chars_within(line.plain, width)
        cut = line.plain.rfind(' ', 0, fits + 1)
        if cut <= indent:
            cut = fits
        pieces.append(line[:cut])
        rest = line[cut + 1:] if line.plain[cut:cut + 1] == ' ' else line[cut:]
        line = Text(' ' * indent) + rest
    return pieces + [line]


def _chars_within(text: str, width: int) -> int:
    """How many leading characters of `text` fit in `width` cells (a wide character takes two)."""
    cells = 0
    for index, char in enumerate(text):
        cells += cell_len(char)
        if cells > width:
            return index
    return len(text)


def hint(*parts: tuple[str, str] | str, color: str = '') -> Text:
    """A title hint from (key, what) pairs and plain strings, joined with " · ":
    hint(('enter', 'edits'), ('space', 'sets')) is "enter edits · space sets". The text is in
    `color` (else `panel-hint`), the keys in `key` bold."""
    text = Text(style=style(color) if color else '')
    for index, part in enumerate(parts):
        if index:
            text.append(' · ')
        if isinstance(part, tuple):
            text.append(part[0], style('key', bold=True))
            text.append(' ' + part[1])
        else:
            text.append(part)
    return text


def pill(text: str, color: str, bg: str) -> Text:
    """A state pill in a panel title (the design's .pill): "calling…", "✓ OK"."""
    return Text.assemble((f' {text} ', style(color, bg, bold=True)))


def waiting(error: str) -> list[Text]:
    """The body of an area whose data isn't in yet: "loading…", or why it failed."""
    if error:
        return [Text(f'✗ could not load it: {error}', style('bad'))]
    return [Text('loading…', style('dim'))]


def side_by_side(columns: list[list[Text]], gap: int = 1) -> list[Text]:
    return [Text(' ' * gap).join(rows) for rows in zip(*columns)]


def split(width: int, weights: tuple[int, ...], gap: int = 1) -> list[int]:
    """`width` cells shared out by `weights`, with `gap` cells between the parts."""
    room = width - gap * (len(weights) - 1)
    widths = [room * weight // sum(weights) for weight in weights]
    widths[-1] += room - sum(widths)
    return widths
