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

"""The activity strip: the three newest things that went out or came back.

Each line is the time, the entry (its kind glyph and name) and what happened, coloured by its cls.
While an entry is open, lines from other tabs are dimmed. A new line is highlighted for
NAV_ACTIVITY_FRESH_S: a green band with a bar in its first cell, red for a failure.
"""

from rich.text import Text

from ros_tui.ui.feedback import ActivityLine
from ros_tui.ui.widgets.base import NavView, band, clickable, fit, glyph, spread, style

FEED_LINES = 3
FEED_NOTES = (':log for everything · click a line to go there', ':log for everything')  # The head's right, as room allows.
WHO_WIDTH = 26  # The kind glyph and the entry name.
LINE_COLORS = {'r': 'bad', 'g': 'ok', 'c': 'live', 'y': 'warn', 'dim': 'dim'}  # By ActivityLine.cls.


def activity_row(line: ActivityLine) -> Text:
    """One activity line: the time, the kind glyph and entry, then what happened (coloured by its cls).
    A click on a line of an entry goes to its tab."""
    who = Text.assemble(glyph(line.kind) if line.kind else '', line.name)
    # The name is cut one cell short, so a long one still keeps a gap before the text.
    row = Text.assemble((line.time, style('dim')), '  ', fit(who, WHO_WIDTH - 1), ' ',
                        (line.text, style(LINE_COLORS.get(line.cls, ''))))
    return clickable(row, ('open', (line.kind, line.name)) if line.kind else None)


class ActivityStrip(NavView):
    DEFAULT_CSS = """
    ActivityStrip { height: auto; background: $rt-strip; padding: 0 1 0 0; }
    """

    def wanted_height(self) -> int:
        """The head and up to FEED_LINES lines (one for "nothing yet")."""
        return 1 + max(1, min(FEED_LINES, len(self.nav.feedback.activity)))

    def get_content_height(self, container, viewport, width) -> int:
        return self.wanted_height()

    def lines(self, width, height):
        nav = self.nav
        title = ' ACTIVITY · ALL TABS' + (' · other tabs dimmed' if nav.tab else '')
        note = next(note for note in FEED_NOTES if len(title) + 1 + len(note) <= width or note == FEED_NOTES[-1])
        head = spread(Text(title, style('feed-head')), Text(note, style('feed-head')), width, optional=True)
        if not nav.feedback.activity:
            return [head, Text(' nothing yet — what you send shows up here', style('dim'))]
        rows = []
        for line in nav.feedback.activity[:FEED_LINES]:
            bad = line.cls == 'r'
            fresh = nav.feedback.is_fresh(line)
            row = Text.assemble(('▍' if fresh else ' ', style('bad' if bad else 'ok')), activity_row(line))
            mine = nav.tab is None or (nav.tab.kind, nav.tab.name) == (line.kind, line.name)
            if not mine:
                row.stylize(style('dim'), 1)
            rows.append(band(row, width, 'fresh-bad-bg' if bad else 'fresh-bg') if fresh else row)
        return [head] + rows
