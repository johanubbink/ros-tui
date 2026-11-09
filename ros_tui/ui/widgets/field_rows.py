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

"""Field rows as panel lines: any entry with a message draws its
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

from ros_tui.ros.schema import within
from ros_tui.ui.entries.base import Area, Editing
from ros_tui.ui.entries.message import MessageEntry
from ros_tui.ui.fields import FieldRows, Row, flat_text
from ros_tui.ui.helpers import helper_name
from ros_tui.ui.keymap import key_for
from ros_tui.ui.nav import AREA, NavState
from ros_tui.ui.values import enum_matches
from ros_tui.ui.widgets.base import HISTORY_KEYS, edit_value, keyed, style
from ros_tui.ui.widgets.panel import Panel, hint, waiting

NUMBER_WIDTH = 3  # The row number column.
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
        typing = editing if editing is not None and editing.row == index else None
        bad = bool(form.bad) and within(form.bad, row.field) and not row.open
        line.append_text(_row_value(row, typing, bad))
        line.append_text(_row_tail(row, typing, form.editable, index == current))
        lines.append(line)
    return lines


def _row_value(row: Row, typing: Editing | None, bad: bool) -> Text:
    """What follows a row's name: the edit box while it is being typed, a folding row's summary, or
    its value coloured by type and a dim enum name. A value the last send check rejected is red."""
    if typing is not None:
        return Text.assemble(': ', edit_value(typing.value, typing.fresh))
    if row.folds:
        return Text(' ' + row.text, style('bad' if bad else 'dim')) if row.text else Text()
    value = Text.assemble(': ', (row.text, style('bad' if bad else VALUE_COLORS[row.style])))
    if row.enum_name:
        value.append(' ' + row.enum_name, style('dim'))
    return value


def _row_tail(row: Row, typing: Editing | None, editable: bool, on: bool) -> Text:
    """What ends a row: an enum being typed shows what the typed text could mean; any other row its
    helper badge (in an editable form, while not being typed, lit when `on`) and its type hint."""
    if typing is not None and row.node.constants:
        return Text('  ' + enum_matches(row.node.constants, typing.value), style('comp'))
    tail = Text()
    name = helper_name(row) if editable and typing is None else None
    if name:
        tail.append('  ')
        tail.append_text(helper_badge(name, on))
    tail.append(f'{HINT_GAP}# {row.hint}', style('syn-hint'))
    return tail


def helper_badge(name: str, on: bool) -> Text:
    """A row's "[f Quaternion]": brighter on the row under the cursor."""
    edge, text = ('key', 'bright') if on else ('hb-edge', 'hb-text')
    badge = Text.assemble(('[', style(edge)), (key_for('helper'), style('key', bold=True)), (f' {name}', style(text)),
                          (']', style(edge)))
    if on:
        badge.stylize(style(bg='hb-on'))
    return badge


def helper_hint(name: str) -> Text:
    """The panel title's "f opens the Quaternion helper", while inside the area on such a row."""
    return keyed(key_for('helper'), f'opens the {name} helper', 'bright')


def shown_value(row: Row) -> Text:
    """A flat row's value as an echo or a result shows it: readable, coloured by type, then a dim
    enum name."""
    text = Text(flat_text(row), style(VALUE_COLORS[row.style]))
    if row.enum_name:
        text.append(' ' + row.enum_name, style('dim'))
    return text


def editor_panel(nav: NavState, entry: MessageEntry, area: Area) -> Panel:
    """The message editor as a panel: its rows, the history and the keys in the title, its errline."""
    count = len(entry.history)
    history = f'history #{entry.hpos + 1}/{count}' if entry.hpos >= 0 else f'history ({count})'
    parts = (((HISTORY_KEYS, history),) if count else ()) + ((key_for('edit'), 'edit'), (key_for('verb', 'paste'), 'paste'))
    inside = nav.layer == AREA and nav.area() == area
    helper = nav.helper_name() if inside else None
    title = Text.assemble(helper_hint(helper), '  ') if helper else Text()
    panel = Panel(area.title, hint=title + hint(*parts), errline=nav.feedback.errline(entry.tab), edits=True)
    if entry.editor is None:
        panel.lines = waiting(entry.error)
        return panel
    editing = nav.editing_in(area.id)
    current = nav.row_index(area) if inside else None
    panel.lines = field_lines(entry.editor, editing, current) or [Text('(no fields)', style('dim'))]
    panel.cursor = nav.row_index(area) if entry.editor.rows() else None
    return panel
