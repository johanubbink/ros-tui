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

"""Field rows as panel lines, as the design's msgArea rows: any entry with a message draws its
`FieldRows` (fields.py) with `field_lines`, one line per row:

    1  a: 19    # int64
    2  ▾ camera_info    # CameraInfo
    3    header: auto    # Header
    4    ▸ d [0 items]    # double[]

the row number, the indent of its depth, ▸ / ▾ on a row that folds, the field name, then its
value coloured by type (numbers, strings), a dim enum name, the `[f Quaternion]` badge of a row with
a field helper, and the type hint. The row being typed shows the edit box instead of its value (an
enum's completion instead of the hint); a value the last send check rejected is red.

`editor_panel` is the whole editor area of a `MessageEntry`: a service's REQUEST, a topic's MESSAGE.
"""

from rich.text import Text

from ros_tui.ui.entries.message import EDITOR, MessageData
from ros_tui.ui.fields import FieldRows, Row, enum_matches, flat_text, within
from ros_tui.ui.helpers import helper_name
from ros_tui.ui.nav import AREA, EDIT, Area, Editing, NavState, Tab
from ros_tui.ui.widgets.base import edit_value, keyed, style
from ros_tui.ui.widgets.panel import Panel, hint, waiting

NUMBER_WIDTH = 3  # The row number column (the design's .ln, 24px).
HINT_GAP = '    '  # Between a value and its "# type" hint.
VALUE_COLORS = {'num': 'syn-num', 'str': 'syn-str', '': 'text'}


def field_lines(form: FieldRows, editing: Editing | None = None, current: int | None = None) -> list[Text]:
    """The rows of `form`; `editing` is the edit in this area, if any (its row shows the edit box),
    and `current` the row under the cursor while inside the area (its helper badge lights up)."""
    fold_slot = form.has_folds()  # Keep names aligned when some rows have ▸ / ▾ in front.
    lines = []
    for index, row in enumerate(form.rows()):
        line = Text.assemble((f'{index + 1:<{NUMBER_WIDTH}}', style('line-no')), '  ' * row.depth)
        if fold_slot:
            line.append(('▾ ' if row.open else '▸ ') if row.folds else '  ', style('grey'))
        line.append(row.key, style('syn-key'))
        bad = bool(form.bad) and within(form.bad, row.field) and not row.open
        typing = editing is not None and editing.row == index
        if typing:
            line.append(': ')
            line.append_text(edit_value(editing.value, editing.fresh))
            if row.node.constants:  # An enum: what the typed text could mean, instead of the type.
                line.append('  ' + enum_matches(row.node.constants, editing.value), style('comp'))
                lines.append(line)
                continue
        elif row.folds:
            if row.text:
                line.append(' ' + row.text, style('bad' if bad else 'dim'))
        else:
            line.append(': ')
            line.append(row.text, style('bad' if bad else VALUE_COLORS[row.style]))
            if row.enum_name:
                line.append(' ' + row.enum_name, style('dim'))
        name = helper_name(row) if form.editable and not typing else None
        if name:
            line.append('  ')
            line.append_text(helper_badge(name, index == current))
        line.append(f'{HINT_GAP}# {row.hint}', style('syn-hint'))
        lines.append(line)
    return lines


def helper_badge(name: str, on: bool) -> Text:
    """A row's "[f Quaternion]" (the design's .hb): brighter on the row under the cursor."""
    edge, text = ('key', 'bright') if on else ('hb-edge', 'hb-text')
    badge = Text.assemble(('[', style(edge)), ('f', style('key', bold=True)), (f' {name}', style(text)),
                          (']', style(edge)))
    if on:
        badge.stylize(style(bg='hb-on'))
    return badge


def helper_hint(name: str) -> Text:
    """The panel title's "f opens the Quaternion helper", while inside the area on such a row."""
    return keyed('f', f'opens the {name} helper', 'bright')


def shown_value(row: Row) -> Text:
    """A flat row's value as an echo or a result shows it: readable, coloured by type, then a dim
    enum name."""
    text = Text(flat_text(row), style(VALUE_COLORS[row.style]))
    if row.enum_name:
        text.append(' ' + row.enum_name, style('dim'))
    return text


def editor_panel(nav: NavState, tab: Tab, data: MessageData, area: Area) -> Panel:
    """The message editor as a panel: its rows, the history and the keys in the title, its errline."""
    count = len(data.history)
    history = f'history #{data.hpos + 1}/{count}' if data.hpos >= 0 else f'history ({count})'
    parts = ((('[ ]', history),) if count else ()) + (('i', 'edit'), ('p', 'paste'))
    inside = nav.layer == AREA and nav.area() == area
    helper = nav.helper_name() if inside else None
    title = Text.assemble(helper_hint(helper), '  ') if helper else Text()
    panel = Panel(area.title, hint=title + hint(*parts), errline=nav.errline(tab), edits=True)
    if data.editor is None:
        panel.lines = waiting(data.error)
        return panel
    editing = nav.editing if nav.layer == EDIT and nav.editing and nav.editing.area == EDITOR else None
    current = nav.row_index(area) if inside else None
    panel.lines = field_lines(data.editor, editing, current) or [Text('(no fields)', style('dim'))]
    panel.cursor = nav.row_index(area) if data.editor.rows() else None
    return panel
