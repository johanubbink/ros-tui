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

"""The top bar (the design's renderTop): the brand, the search hint and what is running."""

from rich.text import Text

from ros_tui.ui.widgets.base import NavView, spread, style


class TopBar(NavView):
    DEFAULT_CSS = """
    TopBar { height: 1; background: $rt-top; }
    """

    def lines(self, width, height):
        left = Text.assemble(
            (' ros_tui ', style('brand', bold=True)), ' ',
            (' / ', style('key', 'term', bold=True)), ('search everything ', style('head', 'term')))
        return [spread(left, self.running(), width)]

    def running(self) -> Text:
        """The running echoes, repeats and goals (◉ ↻ ◐); none exist before step 6."""
        return Text(' ')
