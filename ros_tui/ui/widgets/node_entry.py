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

"""The panels of a node entry: INTERFACES and
PARAMETERS. Everything shown comes from the NodeEntry (entries/node.py)."""

from rich.text import Text

from ros_tui.ui.entries.node import PARAM, NodeEntry, render_value
from ros_tui.ui.nav import NavState
from ros_tui.ui.widgets.base import column_width, edit_value, glyph, style
from ros_tui.ui.widgets.panel import Panel, hint, waiting

NAME_WIDTH = 15  # The parameter name column, at least.
TYPE_WIDTH = 8


def interfaces_panel(nav: NavState, entry: NodeEntry, title: str, row: int) -> Panel:
    panel = Panel(title, hint=hint('enter opens it in a tab'))
    if entry.groups is None:
        panel.lines = waiting(entry.info_error)
        return panel
    if not entry.groups:
        panel.lines = [Text('no interfaces', style('dim'))]
        return panel
    index = 0
    for group, interfaces in entry.groups:
        panel.lines.append(Text('▾ ' + group, style('grey')))
        for interface in interfaces:
            if index == row:
                panel.cursor = len(panel.lines)
            panel.lines.append(Text.assemble('  ', glyph(interface.kind), interface.name))
            index += 1
    return panel


def parameters_panel(nav: NavState, entry: NodeEntry, title: str, row: int) -> Panel:
    panel = Panel(title, hint=hint('● changed', ('space', 'sets'), color='warn') if entry.changes
                  else hint(('enter', 'edits'), ('space', 'sets')), errline=nav.feedback.errline(entry.tab), edits=True)
    if entry.params is None:
        panel.lines = waiting(entry.params_error)
        return panel
    if not entry.params:
        panel.lines = [Text('no parameters', style('dim'))]
        return panel
    name_width = column_width((param.name for param in entry.params), NAME_WIDTH)
    type_width = column_width((param.type for param in entry.params), TYPE_WIDTH)
    editing = nav.editing_in(PARAM)
    for index, param in enumerate(entry.params):
        line = Text.assemble(param.name.ljust(name_width), (param.type.ljust(type_width), style('dim')))
        if editing and editing.row == index:
            line.append_text(edit_value(editing.value, editing.fresh))
        elif param.name in entry.changes:
            line.append(render_value(entry.changes[param.name]), style('warn'))
            line.append(f' was {render_value(param.value)}', style('dim'))
        else:
            line.append(render_value(param.value))
        panel.lines.append(line)
    panel.cursor = row
    return panel


def node_panels(nav: NavState, entry: NodeEntry) -> list[Panel]:
    """INTERFACES and PARAMETERS, in the order of the entry's areas."""
    makers = {'ifs': interfaces_panel, PARAM: parameters_panel}
    return [makers[area.id](nav, entry, area.title, nav.row_index(area)) for area in entry.areas()]
