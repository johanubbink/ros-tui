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

"""The :log view: every activity line, newest first, over a veil.

j k move, gg G go to the newest / oldest, enter goes to that entry's tab, esc closes. The list
scrolls to keep the picked line in the middle.
"""

from rich.text import Text

from ros_tui.ui.nav import LogView
from ros_tui.ui.widgets.activity_strip import activity_row
from ros_tui.ui.widgets.base import BODY_TOP, Overlay, band, cursor_bar, keyed, rule, scroll_top, style

SIDE = 10  # Cells left free on each side.
BOTTOM = 3  # Rows left free above the bottom of the screen (the footer and some of the strip).


class LogPopup(Overlay):
    DEFAULT_CSS = """
    LogPopup { border: round $rt-pop-edge; background: $rt-pop-2; }
    """

    def place(self, width, height):
        if not self.nav.shown(LogView):
            return None
        return SIDE, BODY_TOP, max(10, width - 2 * SIDE), max(5, height - BODY_TOP - BOTTOM)

    def lines(self, width, height):
        nav = self.nav
        activity = nav.feedback.activity
        title = Text.assemble(' ', (f'All activity ({len(activity)})', style('bright', bold=True)), '   ',
                              keyed('j k', 'move'), ('  ·  ', style('dim')), keyed('enter', 'goes there'))
        lines = [title, rule(width)]
        if not activity:
            return lines + [Text(' nothing yet', style('dim'))]
        room = max(1, height - len(lines))
        cur = nav.overlay.cur
        top = scroll_top(cur - room // 2, cur, cur, room, len(activity))
        for index in range(top, min(len(activity), top + room)):
            sel = index == cur
            row = Text.assemble(cursor_bar(sel), activity_row(activity[index]))
            lines.append(band(row, width, 'cursor-on') if sel else row)
        return lines
