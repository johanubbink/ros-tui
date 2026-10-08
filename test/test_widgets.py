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

"""The pure layout helpers of the widgets: fitting the tab row and wrapping long lines."""

import pytest
from rich.text import Text
from ros_tui.ui.widgets.panel import wrapped
from ros_tui.ui.widgets.tab_row import fit_tabs


@pytest.mark.parametrize('widths, want, start, room, shown', [
    ([10] * 5, 0, 0, 100, (0, 5)),  # everything fits
    ([10] * 20, 0, 0, 60, (0, 5)),  # 6 fit, one gives way to "N more ›"
    ([10] * 20, 19, 0, 60, (15, 20)),  # the last tab: "‹ N more" only
    ([10] * 20, 10, 15, 60, (10, 14)),  # moving left: the wanted tab becomes the first shown
    ([10] * 20, 12, 10, 60, (10, 14)),  # still in view: no scroll
])
def test_fit_tabs(widths, want, start, room, shown):
    assert fit_tabs(widths, want, start, room) == shown


def test_long_lines_wrap_at_a_space():
    pieces = wrapped(Text('sequence: [0, 1, 1, 2, 3]'), 14)
    assert [piece.plain for piece in pieces] == ['sequence: [0,', '  1, 1, 2, 3]']
    assert [piece.plain for piece in wrapped(Text('abcdefghij'), 4)] == ['abcd', '  ef', '  gh', '  ij']
    assert [piece.plain for piece in wrapped(Text('名前: 太郎 花子'), 8)] == ['名前:', '  太郎', '  花子']  # Cells, not chars.
