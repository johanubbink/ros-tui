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
- selected ('sel', the area picked on the IN layer): a `key` border, the title on `tab-cur`,
- inside ('in', the AREA and EDIT layers): an `accent-fill` border, the title on `panel-in`, and
  the current row on `row-in` with a `▍` bar in `accent-fill`.

`panel_state` says which one an area is in; `split` and `side_by_side` lay panels out in columns.
"""

from dataclasses import dataclass, field

from rich.text import Text

from ros_tui.ui.nav import AREA, EDIT, IN, NavState
from ros_tui.ui.widgets.base import fit, style

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
    cursor: int | None = None  # The line of the current row; None when the area has no rows.
    errline: str = ''  # Shown under the body, after "✗ ".


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
    room = max(0, height - 3 - (1 if panel.errline else 0))
    top = max(0, panel.cursor - room + 1) if panel.cursor is not None else 0
    body = [_row(panel.lines[i] if i < len(panel.lines) else Text(), inner, state == 'in' and i == panel.cursor)
            for i in range(top, top + room)]
    if panel.errline:
        body.append(fit(Text(' ✗ ' + panel.errline, style('bad', 'err-bg')), inner))
    framed = [Text.assemble(('│', edge), line, ('│', edge)) for line in [fit(title, inner)] + body]
    return [Text('╭' + '─' * inner + '╮', edge)] + framed + [Text('╰' + '─' * inner + '╯', edge)]


def _row(content: Text, width: int, current: bool) -> Text:
    """One body line on the panel background, or the current row's band with its bar."""
    row = Text(style=style(bg='row-in' if current else 'term-2'))
    row.append('▍' if current else ' ', style('accent-fill'))
    row.append_text(content)
    return fit(row, width)


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


def side_by_side(columns: list[list[Text]], gap: int = 1) -> list[Text]:
    return [Text(' ' * gap).join(rows) for rows in zip(*columns)]


def split(width: int, weights: tuple[int, ...], gap: int = 1) -> list[int]:
    """`width` cells shared out by `weights`, with `gap` cells between the parts."""
    room = width - gap * (len(weights) - 1)
    widths = [room * weight // sum(weights) for weight in weights]
    widths[-1] += room - sum(widths)
    return widths
