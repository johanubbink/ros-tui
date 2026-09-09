#!/usr/bin/env python3
# Copyright 2026 Jonas Vervoort
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

"""YAML message editor whose Tab / Shift+Tab hop between fillable values.

Shared by every editor tab (topics/services/actions) via ``InterfaceTab``; the
value-location helpers are pure text logic so they can be unit-tested standalone.
"""

from textual.widgets import TextArea


def _value_locations(text: str) -> list[tuple[int, int]]:
    """Cursor positions of every fillable value in seed YAML (skips parent keys/comments)."""
    locations: list[tuple[int, int]] = []
    for row, line in enumerate(text.splitlines()):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        if stripped.startswith('- ') and stripped[2:].strip():
            locations.append((row, len(line) - len(stripped) + 2))
        elif (separator := line.find(': ')) != -1 and line[separator + 2 :].strip():
            locations.append((row, separator + 2))
    return locations


def first_value_location(text: str) -> tuple[int, int]:
    """Cursor position of the first fillable value in seed YAML, or the start if none."""
    locations = _value_locations(text)
    return locations[0] if locations else (0, 0)


class MessageEditor(TextArea):
    """YAML editor whose Tab / Shift+Tab jump between fillable values instead of indenting."""

    async def _on_key(self, event) -> None:
        if event.key in ('tab', 'shift+tab'):
            event.stop()
            event.prevent_default()
            self._jump_to_value(forward=event.key == 'tab')
            return
        await super()._on_key(event)

    def _jump_to_value(self, forward: bool) -> None:
        locations = _value_locations(self.text)
        if not locations:
            return
        cursor = self.cursor_location
        if forward:
            target = next((loc for loc in locations if loc > cursor), locations[0])
        else:
            earlier = [loc for loc in locations if loc < cursor]
            target = earlier[-1] if earlier else locations[-1]
        self.move_cursor(target)
