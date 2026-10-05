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

"""The toast (the design's renderToast): one short line, bottom right of the body, for NAV_TOAST_S.

ok is green, bad red, info blue (docs/design-principles.md, "State markers"). It lives in the body,
so the search veil dims it like the design's z-order does. NavState.tick() takes it away.
"""

from rich.cells import cell_len
from rich.text import Text

from ros_tui.ui.widgets.base import Overlay, style

LOOKS = {'': ('ok', 'ok-bg'), 'ok': ('ok', 'ok-bg'), 'bad': ('bad', 'bad-bg'), 'info': ('info', 'panel-in')}
RIGHT = 1  # Cells kept free on its right.


class ToastView(Overlay):
    def place(self, width, height):
        toast = self.nav.toast
        if toast is None:
            return None
        w = min(width, cell_len(toast.text) + 2)
        return max(0, width - w - RIGHT), max(0, height - 1), w, 1

    def lines(self, width, height):
        toast = self.nav.toast
        color, bg = LOOKS[toast.kind]
        return [Text(f' {toast.text} ', style(color, bg, bold=True))]
