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
value coloured by type (numbers, strings), a dim enum name, and the type hint. The row being typed
shows the edit box instead of its value; a value the last send check rejected is red.
"""

from rich.text import Text

from ros_tui.ui.fields import FieldRows, within
from ros_tui.ui.nav import Editing
from ros_tui.ui.widgets.base import edit_value, style

NUMBER_WIDTH = 3  # The row number column (the design's .ln, 24px).
HINT_GAP = '    '  # Between a value and its "# type" hint.
VALUE_COLORS = {'num': 'syn-num', 'str': 'syn-str', '': 'text'}


def field_lines(form: FieldRows, editing: Editing | None = None) -> list[Text]:
    """The rows of `form`; `editing` is the edit in this area, if any (its row shows the edit box)."""
    fold_slot = form.has_folds()  # Keep names aligned when some rows have ▸ / ▾ in front.
    lines = []
    for index, row in enumerate(form.rows()):
        line = Text.assemble((f'{index + 1:<{NUMBER_WIDTH}}', style('line-no')), '  ' * row.depth)
        if fold_slot:
            line.append(('▾ ' if row.open else '▸ ') if row.folds else '  ', style('grey'))
        line.append(row.key, style('syn-key'))
        bad = bool(form.bad) and within(form.bad, row.field) and not row.open
        if editing is not None and editing.row == index:
            line.append(': ')
            line.append_text(edit_value(editing.value, editing.fresh))
        elif row.folds:
            if row.text:
                line.append(' ' + row.text, style('bad' if bad else 'dim'))
        else:
            line.append(': ')
            line.append(row.text, style('bad' if bad else VALUE_COLORS[row.style]))
            if row.enum_name:
                line.append(' ' + row.enum_name, style('dim'))
        # Step 8 adds the "[f …]" badge of a row with a field helper here.
        line.append(f'{HINT_GAP}# {row.hint}', style('syn-hint'))
        lines.append(line)
    return lines
