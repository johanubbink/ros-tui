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

"""``ModeForm`` — a composed "radio mode-selector + per-mode input rows" widget.

The Quaternion and Time wizards both let you enter the same value several ways (raw vs euler
vs axis-angle; seconds vs wall-clock vs relative). This widget captures that shared shape:
a RadioSet of modes plus one input-row group per mode, showing only the active mode's rows.
A wizard *composes* one and reads ``current_mode`` / ``raw(field_id)`` in ``build_value`` —
no inheritance. ``Changed`` fires on a mode switch or a row edit so the wizard can refresh a
live preview.
"""

from typing import Sequence

from textual import on
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, RadioButton, RadioSet, Static

# A mode is (key, label, rows); a row is (field_id, label, value, placeholder). The 'now'-style
# modes with no inputs pass an empty rows tuple.
Row = tuple[str, str, str, str]
Mode = tuple[str, str, tuple[Row, ...]]


def pressed_key(radio_set: RadioSet, keys: Sequence[str]) -> str:
    """The key of the pressed radio button, falling back to the first key."""
    index = radio_set.pressed_index
    return keys[index] if 0 <= index < len(keys) else keys[0]


class ModeForm(Widget):
    """Radio mode-selector plus per-mode input rows; only the active mode's rows are shown."""

    class Changed(Message):
        """The mode changed or a field was edited."""

    DEFAULT_CSS = """
    ModeForm { height: auto; }
    """

    def __init__(self, modes: list[Mode], *, radio_id: str, initial: str | None = None):
        super().__init__()
        self._modes = list(modes)
        self._keys = [key for key, _, _ in self._modes]
        self._radio_id = radio_id
        self._initial = initial or self._keys[0]

    def compose(self):
        with RadioSet(id=self._radio_id):
            for key, label, _ in self._modes:
                yield RadioButton(label, value=key == self._initial)
        for key, _, rows in self._modes:
            for field_id, label, value, placeholder in rows:
                with Horizontal(classes=f'field-row mode-{key}', id=f'{field_id}-row'):
                    yield Static(label)
                    yield Input(value=value, placeholder=placeholder, id=field_id)

    def on_mount(self) -> None:
        self._refresh_visibility()

    @property
    def current_mode(self) -> str:
        return pressed_key(self.query_one(f'#{self._radio_id}', RadioSet), self._keys)

    def raw(self, field_id: str) -> str:
        """The current text of a row's input."""
        return self.query_one(f'#{field_id}', Input).value

    def _refresh_visibility(self) -> None:
        mode = self.current_mode
        for key in self._keys:
            for row in self.query(f'.mode-{key}'):
                row.display = key == mode

    @on(RadioSet.Changed)
    def _mode_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._refresh_visibility()
        self.post_message(self.Changed())

    @on(Input.Changed)
    def _input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.post_message(self.Changed())
