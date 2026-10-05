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

"""The activity strip (the design's renderFeed): the three newest things that went out or came back."""

from rich.text import Text

from ros_tui.ui.widgets.base import NavView, fit, glyph, spread, style

FEED_LINES = 3
WHO_WIDTH = 26  # The kind glyph and the entry name.
LINE_COLORS = {'r': 'bad', 'g': 'ok'}  # By ActivityLine.cls, as the design's .r / .g classes.


class ActivityStrip(NavView):
    DEFAULT_CSS = """
    ActivityStrip { height: auto; background: $rt-strip; padding: 0 1; }
    """

    def get_content_height(self, container, viewport, width) -> int:
        return 1 + max(1, min(FEED_LINES, len(self.nav.activity)))

    def lines(self, width, height):
        nav = self.nav
        title = 'ACTIVITY · ALL TABS' + (' · other tabs dimmed' if nav.tab else '')
        head = spread(Text(title, style('feed-head')), Text(':log for everything', style('feed-head')), width)
        if not nav.activity:
            return [head, Text('nothing yet — what you send shows up here', style('dim'))]
        rows = []
        for line in nav.activity[:FEED_LINES]:
            who = Text.assemble(glyph(line.kind) if line.kind else '', line.name)
            row = Text.assemble(fit(who, WHO_WIDTH), (line.text, style(LINE_COLORS.get(line.cls, ''))))
            mine = nav.tab is None or (nav.tab.kind, nav.tab.name) == (line.kind, line.name)
            if not mine:
                row.stylize(style('dim'))
            rows.append(row)
        return [head] + rows
