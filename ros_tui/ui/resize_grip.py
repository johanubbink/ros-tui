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

"""The seam: a 1-cell divider you can grab to widen/narrow the pane on its left.

Textual has no built-in splitter, so this is the standard mouse-capture pattern its own
scrollbars use: on mouse-down we capture the mouse (so every move/up routes here even when
the cursor is over the list), translate the horizontal travel into a new cell width for the
target pane, and clamp it. The right pane stays ``1fr`` and absorbs the difference. See
``docs/STYLE_GUIDE.md``.
"""

from textual import events
from textual.widget import Widget
from textual.widgets import Static

from ros_tui.constants import LIST_MIN_WIDTH, RIGHT_PANE_MIN_WIDTH


class ResizeGrip(Static):
    """A draggable vertical handle that resizes ``target`` (the pane to its left)."""

    DEFAULT_CSS = """
    ResizeGrip {
        width: 1;
        height: 1fr;
        background: $surface-lighten-2;
        color: $text-muted;
        content-align: center middle;
    }
    ResizeGrip:hover, ResizeGrip.-active { background: $primary; color: $background; }
    """

    def __init__(self, target: Widget, **kwargs):
        super().__init__('┊', **kwargs)
        self._target = target
        self._start_x = 0
        self._start_width = 0
        self._dragging = False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.capture_mouse()
        self.add_class('-active')
        self._dragging = True
        self._start_x = event.screen_x
        # outer_size is the border-box width, which is what styles.width sets — recording
        # the content size (self._target.size) instead would jump the pane by its border.
        self._start_width = self._target.outer_size.width
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        # screen_x stays in a stable frame; widget-relative x goes negative once captured.
        new_width = self._start_width + (event.screen_x - self._start_x)
        # Clamp so neither pane collapses; the outer max() guards a terminal too narrow to
        # honour both minimums (otherwise the range would invert and force the list too wide).
        max_width = max(LIST_MIN_WIDTH, self.app.size.width - 1 - RIGHT_PANE_MIN_WIDTH)
        new_width = max(LIST_MIN_WIDTH, min(max_width, new_width))
        if new_width != self._target.outer_size.width:  # skip no-op reflows during a drag
            self._target.styles.width = new_width  # cells -> reflows immediately
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        self.release_mouse()
        self.remove_class('-active')
        self._dragging = False
        event.stop()
