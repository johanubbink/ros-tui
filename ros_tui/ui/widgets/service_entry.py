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

"""The service entry's button row and panels:
"▶ Call space", then REQUEST (field rows) and RESPONSE side by side. Everything shown comes from
the ServiceEntry (entries/service.py)."""

from rich.text import Text

from ros_tui.ui.entries.base import Area
from ros_tui.ui.entries.message import EDITOR
from ros_tui.ui.entries.service import ServiceEntry
from ros_tui.ui.nav import NavState
from ros_tui.ui.widgets.base import button, keyed, primary_look, spread, style
from ros_tui.ui.widgets.field_rows import editor_panel, field_lines
from ros_tui.ui.widgets.panel import Panel, pill


def service_toolbar(nav: NavState, entry: ServiceEntry, width: int) -> Text:
    """The button row: the Call button with its key, and where earlier requests are."""
    return spread(button('▶ Call', 'space', primary_look(nav, entry.tab, 'pri')), keyed('[ ]', 'earlier requests', 'dim'),
                  width, optional=True)


def response_panel(nav: NavState, entry: ServiceEntry, area: Area) -> Panel:
    call = entry.call
    panel = Panel(area.title)
    if call is None:
        panel.hint = Text('not called yet')
        return panel
    if not call.done:
        panel.hint = pill('calling…', 'live')
        panel.lines = [Text('waiting for the response…', style('dim'))]
        return panel
    timing = Text(f' {call.elapsed_ms:.1f} ms')
    if call.error:
        panel.hint = pill('✗ FAILED', 'bad') + timing
        panel.errline = f'call failed: {call.error}'
        return panel
    panel.hint = pill('✓ OK', 'ok') + timing
    rows = entry.response.rows() if entry.response else []
    panel.lines = field_lines(entry.response) if rows else [Text('empty response (no fields)', style('dim'))]
    panel.cursor = nav.row_index(area) if rows else None
    return panel


def service_panels(nav: NavState, entry: ServiceEntry) -> list[Panel]:
    """REQUEST and RESPONSE, in the order of the entry's areas."""
    makers = {EDITOR: editor_panel, 'out': response_panel}
    return [makers[area.id](nav, entry, area) for area in entry.areas()]
