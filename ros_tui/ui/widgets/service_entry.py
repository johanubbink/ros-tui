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

"""The service entry's button row and panels (the services branch of the design's renderEntry):
"▶ Call space", then REQUEST (field rows) and RESPONSE side by side. Everything shown comes from
the ServiceEntry provider (entries/service.py)."""

from rich.text import Text

from ros_tui.ui.entries.message import EDITOR
from ros_tui.ui.entries.service import ServiceData
from ros_tui.ui.nav import EDIT, Area, NavState, Tab
from ros_tui.ui.widgets.base import spread, style
from ros_tui.ui.widgets.field_rows import field_lines
from ros_tui.ui.widgets.panel import Panel, hint, pill, waiting


def service_toolbar(nav: NavState, tab: Tab, width: int) -> Text:
    """The button row: the Call button with its key, and where earlier requests are."""
    button = Text.assemble((' ▶ Call ', style('bright', 'accent-fill', bold=True)),
                           ('space ', style('key', 'accent-fill')))
    return spread(button, Text.assemble(('[ ]', style('key', bold=True)), (' earlier requests', style('dim'))), width)


def request_panel(nav: NavState, tab: Tab, data: ServiceData, area: Area) -> Panel:
    count = len(data.history)
    history = f'history #{data.hpos + 1}/{count}' if data.hpos >= 0 else f'history ({count})'
    parts = ((('[ ]', history),) if count else ()) + (('i', 'edit'), ('p', 'paste'))
    panel = Panel(area.title, hint=hint(*parts), errline=nav.errline(tab))
    if data.editor is None:
        panel.lines = waiting(data.error)
        return panel
    editing = nav.editing if nav.layer == EDIT and nav.editing and nav.editing.area == EDITOR else None
    panel.lines = field_lines(data.editor, editing) or [Text('(no fields)', style('dim'))]
    panel.cursor = nav.row_index(area) if data.editor.rows() else None
    return panel


def response_panel(nav: NavState, tab: Tab, data: ServiceData, area: Area) -> Panel:
    call = data.call
    panel = Panel(area.title)
    if call is None:
        panel.hint = Text('not called yet')
        return panel
    if not call.done:
        panel.hint = pill('calling…', 'live', 'live-bg')
        panel.lines = [Text('waiting for the response…', style('dim'))]
        return panel
    timing = Text(f' {call.elapsed_ms:.1f} ms')
    if call.error:
        panel.hint = pill('✗ FAILED', 'bad', 'bad-bg') + timing
        panel.errline = f'call failed: {call.error}'
        return panel
    panel.hint = pill('✓ OK', 'ok', 'ok-bg') + timing
    rows = data.response.rows() if data.response else []
    panel.lines = field_lines(data.response) if rows else [Text('empty response (no fields)', style('dim'))]
    panel.cursor = nav.row_index(area) if rows else None
    return panel


def service_panels(nav: NavState, tab: Tab) -> list[Panel]:
    """REQUEST and RESPONSE, in the order of the entry's areas."""
    data = nav.provider.for_tab(tab).data(tab)
    makers = {EDITOR: request_panel, 'out': response_panel}
    return [makers[area.id](nav, tab, data, area) for area in nav.areas()]
