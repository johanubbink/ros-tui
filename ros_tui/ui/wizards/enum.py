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

"""Enum wizard — pick an integer value from a field's message constants."""

from typing import Any, Iterable

from textual.widget import Widget
from textual.widgets import RadioButton, RadioSet, Static

from ros_tui.ui.wizards.base import WizardScreen


class EnumWizardPopup(WizardScreen):
    """Pick an integer enum value from a field's constants. Dismisses with the int, or None.

    The constants ``(name, value)`` are single-choice options rendered ``NAME = value`` in a
    RadioSet -- the same selection primitive the other wizards use, so all values (and their
    underlying integers) are visible at once and it scales to large enums. Unlike the other
    wizards it is not keyed by type label: ``matched_wizard`` binds the field's ``constants`` into
    the factory, so this popup is reached for any integer field that carries enum constants.
    """

    TITLE = 'Select a value'
    PREFIX = 'enum-wizard'

    DEFAULT_CSS = """
    EnumWizardPopup RadioSet { max-height: 20; }
    """

    def __init__(self, current_value: Any = None, *, choices: tuple[tuple[str, int], ...]):
        super().__init__()
        self._choices = tuple(choices)
        # Preselect the constant matching the current value, else the first.
        self._selected = next(
            (index for index, (_, value) in enumerate(self._choices) if value == current_value),
            0,
        )

    def compose_body(self) -> Iterable[Widget]:
        with RadioSet(id='enum-wizard-choices'):
            for index, (name, value) in enumerate(self._choices):
                yield RadioButton(f'{name} = {value}', value=index == self._selected)

    def build_value(self) -> Any:
        index = self.query_one('#enum-wizard-choices', RadioSet).pressed_index
        if 0 <= index < len(self._choices):
            return self._choices[index][1]
        return None
