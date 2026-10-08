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

"""The toast: one short line, bottom right of the body, for NAV_TOAST_S.

ok is green, bad red, info blue (docs/design-principles.md, "State markers"). It lives in the body,
so the search veil dims it. NavState.tick() takes it away.
"""

from rich.cells import cell_len

from ros_tui.ui.widgets.base import Overlay
from ros_tui.ui.widgets.panel import pill

RIGHT = 1  # Cells kept free on its right.


class ToastView(Overlay):
    modal = False  # It never has the keys: a click on it doesn't close a popup.

    def place(self, width, height):
        toast = self.nav.feedback.toast
        if toast is None:
            return None
        w = min(width, cell_len(toast.text) + 2)
        return max(0, width - w - RIGHT), max(0, height - 1), w, 1

    def lines(self, width, height):
        toast = self.nav.feedback.toast
        return [pill(toast.text, toast.kind or 'ok')]
