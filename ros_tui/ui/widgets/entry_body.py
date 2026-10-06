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

"""An open entry (the design's renderEntry): its header, then its areas as panels.

The header is the kind tag, the name and the type (a node's namespace, and a topic's Echo / Publish
switch), then the entry's button row (`TOOLBARS`), if it has one. Each area is a `Panel`
(widgets/panel.py), drawn selected on the IN layer and inside on the AREA and EDIT layers. An entry
kind has its renderer in `RENDERERS`.
"""

from typing import Callable

from rich.text import Text

from ros_tui.ui.nav import NavState, Tab
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.action_entry import action_panels, action_toolbar
from ros_tui.ui.widgets.base import NavView, fit, spread, style
from ros_tui.ui.widgets.node_entry import node_panels
from ros_tui.ui.widgets.panel import Panel, draw_panel, panel_state, side_by_side, split
from ros_tui.ui.widgets.service_entry import service_panels, service_toolbar
from ros_tui.ui.widgets.topic_entry import topic_counts, topic_panels, topic_toolbar

# Width shares of the panels side by side (else equal). Actions are 2:1 in the design; 3:2 keeps RESULT's
# "EXECUTING 2.4 s · live feedback" title whole at 124 columns.
PANEL_WEIGHTS = {'actions': (3, 2), 'nodes': (10, 11)}

# Entry kind -> its panels, one per area in the order of nav.areas().
RENDERERS: dict[str, Callable[[NavState, Tab], list[Panel]]] = {
    'nodes': node_panels, 'services': service_panels, 'topics': topic_panels, 'actions': action_panels}
# Entry kind -> its button row under the header (else a blank line).
TOOLBARS: dict[str, Callable[[NavState, Tab, int], Text]] = {
    'services': service_toolbar, 'topics': topic_toolbar, 'actions': action_toolbar}
# Entry kind -> a note after the type in the header (a topic's "1 pub · 0 sub").
NOTES: dict[str, Callable[[NavState, Tab], Text]] = {'topics': topic_counts}


class EntryBody(NavView):
    DEFAULT_CSS = """
    EntryBody { height: 1fr; }
    """

    def header(self, width: int) -> Text:
        nav = self.nav
        tab = nav.tab
        kind = KINDS[tab.kind]
        item = nav.item(tab)
        left = Text.assemble(
            (f' {kind.glyph} {kind.one.upper()} ', style(kind.color, kind.tag_bg)), '  ',
            (tab.name, style('accent', bold=True)), '  ', (item.type if item else '', style('muted')))
        note = NOTES.get(tab.kind)
        if note:
            left.append('  ')
            left.append_text(note(nav, tab))
        mode = nav.entry_mode()
        if mode is None:
            return fit(left, width)
        switch = Text.assemble(*((f' {label} ', style('bright', 'cursor', bold=True) if mode == label.lower()
                                  else style('grey', 'term-3')) for label in ('Echo', 'Publish')),
                               ' ', ('e', style('key', bold=True)))
        return spread(left, switch, width)

    def lines(self, width, height):
        nav = self.nav
        tab = nav.tab
        if tab is None:
            return []
        panels = RENDERERS[tab.kind](nav, tab)
        widths = split(width, PANEL_WEIGHTS.get(tab.kind, (1,) * len(panels)))
        drawn = [draw_panel(panel, w, height - 2, panel_state(nav, index))
                 for index, (panel, w) in enumerate(zip(panels, widths))]
        toolbar = TOOLBARS.get(tab.kind)
        return [self.header(width), toolbar(nav, tab, width) if toolbar else Text()] + side_by_side(drawn)
