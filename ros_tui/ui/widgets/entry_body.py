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

"""An open entry: its header, then its areas as panels.

The header is the kind tag, the name and the type (a node's namespace, and the switch of an entry
with modes: a topic's Echo / Publish), then, after a blank line, the entry's button row, if it
has one, and a blank line before the panels. Each area is a `Panel` (widgets/panel.py), drawn
selected on the IN layer and inside on the AREA and EDIT layers. An entry kind has its view in
`VIEWS`. A click on a panel goes inside its area, a click on the switch picks that mode.
"""

from dataclasses import dataclass
from typing import Any, Callable

from rich.text import Text

from ros_tui.ui.entries.base import Entry
from ros_tui.ui.nav import NavState
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.action_entry import action_panels, action_toolbar
from ros_tui.ui.widgets.base import NavView, clickable, fit, spread, style, switch
from ros_tui.ui.widgets.node_entry import node_panels
from ros_tui.ui.widgets.panel import Panel, cursor_line, draw_panel, panel_state, side_by_side, split
from ros_tui.ui.widgets.service_entry import service_panels, service_toolbar
from ros_tui.ui.widgets.topic_entry import topic_counts, topic_panels, topic_toolbar


@dataclass(frozen=True)
class EntryView:
    """How an entry kind is drawn."""

    panels: Callable[[NavState, Any], list[Panel]]  # One per area, in the order of the entry's areas().
    toolbar: Callable[[NavState, Any, int], Text] | None = None  # The button row under the header.
    note: Callable[[NavState, Any], Text] | None = None  # After the type in the header (a topic's "1 pub · 0 sub").
    weights: tuple[int, ...] | None = None  # Width shares of the panels side by side (else equal).


# 3:2 keeps RESULT's "EXECUTING 2.4 s · live feedback" title whole at 124 columns.
VIEWS = {
    'topics': EntryView(topic_panels, topic_toolbar, topic_counts),
    'services': EntryView(service_panels, service_toolbar),
    'actions': EntryView(action_panels, action_toolbar, weights=(3, 2)),
    'nodes': EntryView(node_panels, weights=(10, 11)),
}


class EntryBody(NavView):
    DEFAULT_CSS = """
    EntryBody { height: 1fr; }
    """

    def header(self, entry: Entry, width: int) -> Text:
        nav = self.nav
        tab = entry.tab
        kind = KINDS[tab.kind]
        item = nav.catalog.item(tab)
        left = Text.assemble(
            (f' {kind.glyph} {kind.one.upper()} ', style(kind.color, kind.tag_bg)), '  ',
            (tab.name, style('accent', bold=True)), '  ', (item.type if item else '', style('muted')))
        note = VIEWS[tab.kind].note
        if note:
            left.append('  ')
            left.append_text(note(nav, entry))
        if not entry.modes():
            return fit(left, width)
        modes = switch(*((mode.capitalize(), mode == entry.mode, ('mode', mode)) for mode in entry.modes()))
        return spread(left, modes + Text.assemble(' ', ('e', style('key', bold=True))), width)

    def lines(self, width, height):
        nav = self.nav
        if nav.tab is None:
            return []
        entry = nav.entry(nav.tab)
        view = VIEWS[entry.tab.kind]
        panels = view.panels(nav, entry)
        widths = panel_widths(view, panels, width)
        top = head_lines(view)
        drawn = [[clickable(line, ('area', index)) for line in draw_panel(panel, w, height - top, panel_state(nav, index))]
                 for index, (panel, w) in enumerate(zip(panels, widths))]
        head = [self.header(entry, width), Text()] + ([view.toolbar(nav, entry, width), Text()] if view.toolbar else [])
        return head + side_by_side(drawn)


def head_lines(view: EntryView) -> int:
    """Lines above the panels: the header and a blank line, then the toolbar and a blank line."""
    return 4 if view.toolbar else 2


def panel_widths(view: EntryView, panels: list[Panel], width: int) -> list[int]:
    return split(width, view.weights or (1,) * len(panels))


def row_line(nav: NavState, width: int, height: int) -> int | None:
    """The line of an EntryBody of `width` x `height` that the current area's current row ends on,
    or None (no open entry, or its area has no current row). The field helper popup goes under it."""
    if nav.tab is None:
        return None
    entry = nav.entry(nav.tab)
    view = VIEWS[entry.tab.kind]
    panels = view.panels(nav, entry)
    index = nav.area_index()
    if not 0 <= index < len(panels):
        return None
    top = head_lines(view)
    line = cursor_line(panels[index], panel_widths(view, panels, width)[index], height - top)
    return None if line is None else top + line
