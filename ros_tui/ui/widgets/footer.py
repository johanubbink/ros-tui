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

"""The footer (the design's renderFoot): mode badge, pending prefix, breadcrumb, then esc / enter.

Everything in it comes from `NavState.footer()`; this only lays it out. While the command line is
open it replaces the footer: COMMAND, the typed `:text` and how to use it (the suggestions are
widgets/command_suggestions.py).
"""

from rich.text import Text

from ros_tui.ui.theme import MODES
from ros_tui.ui.widgets.base import NavView, cursor_cell, keyed, spread, style

COMMAND_HINT = '↑↓ pick · tab completes · enter runs · esc cancels'


class Footer(NavView):
    DEFAULT_CSS = """
    Footer { height: 1; background: $rt-foot; }
    """

    @property
    def modal(self) -> bool:
        """While it is the command line it is that popup: a click on it doesn't close it."""
        return self.nav.cmd is not None

    def lines(self, width, height):
        foot = self.nav.footer()
        left = Text.assemble((f' {foot.mode.upper()} ', style('mode-text', MODES[foot.mode], bold=True)), ' ')
        if self.nav.cmd:
            left.append_text(Text.assemble((':' + self.nav.cmd.q, style('bright')), cursor_cell()))
            return [spread(left, Text(COMMAND_HINT + ' ', style('dim')), width)]
        if foot.pending:
            left.append_text(keyed(f'{foot.pending}…', ''))
            left.append(' ')
        for index, part in enumerate(foot.path):
            if index:
                left.append(' › ', style('sep'))
            last = index == len(foot.path) - 1
            left.append(part, style('bright', bold=True) if last else style('head'))
        right = Text()
        for key, label, color in (('esc', foot.esc, 'grey'), ('enter', foot.enter, 'grey'),
                                  ('f', foot.helper and f'{foot.helper} helper', 'bright'), ('?', 'keys', 'grey')):
            if label:
                right.append_text(keyed(key, label, color))
                right.append('  ')
        return [spread(left, right, width)]
