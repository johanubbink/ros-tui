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

"""The command line's suggestions (the design's .cmdsug): above the footer, bottom left.

The command line itself replaces the footer row (widgets/footer.py). This lists up to
keymap.MAX_SUGGESTIONS commands that match what is typed; the picked one is highlighted.
"""

from rich.text import Text

from ros_tui.ui.widgets.base import Overlay, band, fit, style

MIN_WIDTH = 46  # The design's min-width: 360px.
NAME_WIDTH = 10  # The command column (min-width: 80px).


class CommandSuggestions(Overlay):
    DEFAULT_CSS = """
    CommandSuggestions { border: round $rt-cmd-edge; background: $rt-cmd-bg; }
    """

    def place(self, width, height):
        suggestions = self.nav.cmd_suggestions() if self.nav.cmd else []
        if not suggestions:
            return None
        widest = max(len(text) for _, text in suggestions) + NAME_WIDTH + 5  # Lead, gap and border.
        w = min(width - 2, max(MIN_WIDTH, widest))
        h = len(suggestions) + 2
        return 1, max(0, height - 1 - h), w, h

    def lines(self, width, height):
        lines = []
        for index, (name, text) in enumerate(self.nav.cmd_suggestions()):
            line = Text.assemble(' ', fit(Text(':' + name, style('key', bold=True)), NAME_WIDTH), '  ',
                                 (text, style('grey')))
            lines.append(band(line, width, 'cmd-sel') if index == self.nav.cmd.cur else line)
        return lines
