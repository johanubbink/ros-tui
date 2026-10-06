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

"""The panels of a node entry (the nodes branch of the design's renderEntry): INTERFACES and
PARAMETERS. Everything shown comes from the NodeEntry provider (entries/node.py)."""

from rich.text import Text

from ros_tui.ui.entries.node import PARAM, NodeData, render_value
from ros_tui.ui.nav import EDIT, NavState, Tab
from ros_tui.ui.widgets.base import edit_value, glyph, style
from ros_tui.ui.widgets.panel import Panel, hint

NAME_WIDTH = 15  # The parameter name column, at least (the design's padEnd(15)).
TYPE_WIDTH = 8


def _waiting(data_error: str) -> list[Text]:
    if data_error:
        return [Text(f'✗ could not load it: {data_error}', style('bad'))]
    return [Text('loading…', style('dim'))]


def interfaces_panel(nav: NavState, tab: Tab, data: NodeData, title: str, row: int) -> Panel:
    panel = Panel(title, hint=hint('enter opens it in a tab'))
    if data.groups is None:
        panel.lines = _waiting(data.info_error)
        return panel
    if not data.groups:
        panel.lines = [Text('no interfaces', style('dim'))]
        return panel
    index = 0
    for group, interfaces in data.groups:
        panel.lines.append(Text('▾ ' + group, style('grey')))
        for interface in interfaces:
            if index == row:
                panel.cursor = len(panel.lines)
            panel.lines.append(Text.assemble('  ', glyph(interface.kind), interface.name))
            index += 1
    return panel


def parameters_panel(nav: NavState, tab: Tab, data: NodeData, title: str, row: int) -> Panel:
    panel = Panel(title, hint=hint('● changed', ('space', 'sets'), color='warn') if data.changes
                  else hint(('enter', 'edits'), ('space', 'sets')), errline=nav.errline(tab))
    if data.params is None:
        panel.lines = _waiting(data.params_error)
        return panel
    if not data.params:
        panel.lines = [Text('no parameters', style('dim'))]
        return panel
    name_width = max(NAME_WIDTH, *(len(param.name) + 1 for param in data.params))
    type_width = max(TYPE_WIDTH, *(len(param.type) + 1 for param in data.params))
    editing = nav.editing if nav.layer == EDIT and nav.editing and nav.editing.area == PARAM else None
    for index, param in enumerate(data.params):
        line = Text.assemble(param.name.ljust(name_width), (param.type.ljust(type_width), style('dim')))
        if editing and editing.row == index:
            line.append_text(edit_value(editing.value, editing.fresh))
        elif param.name in data.changes:
            line.append(render_value(data.changes[param.name]), style('warn'))
            line.append(f' was {render_value(param.value)}', style('dim'))
        else:
            line.append(render_value(param.value))
        panel.lines.append(line)
    panel.cursor = row
    return panel


def node_panels(nav: NavState, tab: Tab) -> list[Panel]:
    """INTERFACES and PARAMETERS, in the order of the entry's areas."""
    data = nav.provider.for_tab(tab).data(tab)
    makers = {'ifs': interfaces_panel, PARAM: parameters_panel}
    return [makers[area.id](nav, tab, data, area.title, nav.row_index(area)) for area in nav.areas()]
