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

"""An open entry (the design's renderEntry), for now a placeholder: its header and its areas.

The header is the kind tag, the name and the type (and a topic's Echo / Publish switch). Each
area is an empty panel with its title, so picking an area (layer `in`: white border) and going
inside it (layer `area`: blue border) show. The entry kinds fill the panels in later steps.
"""

from rich.text import Text

from ros_tui.ui.nav import AREA, EDIT, IN
from ros_tui.ui.theme import KINDS
from ros_tui.ui.widgets.base import NavView, fit, spread, style

PANEL_LOOKS = {  # panel state -> (border colour, title background)
    '': ('tline', 'term-3'),
    'sel': ('key', 'tab-cur'),
    'in': ('accent-fill', 'panel-in'),
}
PANEL_WEIGHTS = {'actions': (2, 1), 'nodes': (10, 11)}  # Width shares of the panels side by side (else equal).
PLACEHOLDER = 'nothing here yet — this entry is built in a later step'


def panel(title: str, body: list[Text], width: int, height: int, state: str = '') -> list[Text]:
    """A bordered panel of `width` x `height` cells: a title bar, then the body rows."""
    border, title_bg = PANEL_LOOKS[state]
    edge = style(border)
    inner = max(0, width - 2)
    lines = [Text('╭' + '─' * inner + '╮', edge),
             Text.assemble(('│', edge), fit(Text(' ' + title, style('label', title_bg, bold=True)), inner, title_bg),
                           ('│', edge))]
    for row in range(max(0, height - 3)):
        content = fit(Text(' ') + (body[row] if row < len(body) else Text()), inner)
        content.stylize(style(bg='term-2'))
        lines.append(Text.assemble(('│', edge), content, ('│', edge)))
    lines.append(Text('╰' + '─' * inner + '╯', edge))
    return lines


def side_by_side(columns: list[list[Text]], gap: int = 1) -> list[Text]:
    return [Text(' ' * gap).join(rows) for rows in zip(*columns)]


def split(width: int, weights: tuple[int, ...], gap: int = 1) -> list[int]:
    """`width` cells shared out by `weights`, with `gap` cells between the parts."""
    room = width - gap * (len(weights) - 1)
    widths = [room * weight // sum(weights) for weight in weights]
    widths[-1] += room - sum(widths)
    return widths


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
        mode = nav.entry_mode()
        if mode is None:
            return fit(left, width)
        switch = Text.assemble(*((f' {label} ', style('bright', 'cursor', bold=True) if mode == label.lower()
                                  else style('grey', 'term-3')) for label in ('Echo', 'Publish')),
                               ' ', ('e', style('key', bold=True)))
        return spread(left, switch, width)

    def lines(self, width, height):
        nav = self.nav
        if nav.tab is None:
            return []
        areas = nav.areas()
        picked = nav.area_index()
        here = {IN: 'sel', AREA: 'in', EDIT: 'in'}.get(nav.layer, '')
        body = [Text(PLACEHOLDER, style('dim'))]
        widths = split(width, PANEL_WEIGHTS.get(nav.tab.kind, (1,) * len(areas)))
        panels = [panel(area.title, body, w, height - 2, here if index == picked else '')
                  for index, (area, w) in enumerate(zip(areas, widths))]
        return [self.header(width), Text()] + side_by_side(panels)
