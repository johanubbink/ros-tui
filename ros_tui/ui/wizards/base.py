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

"""``WizardScreen`` — the shared modal shell every field wizard is built on.

The shell owns the parts all wizards repeat verbatim: the modal box, the escape binding, the
Apply/Cancel buttons and their handlers, the error line, and the common CSS. A subclass sets
``TITLE`` + ``PREFIX`` and fills in only what varies:

* ``compose_body()`` — yield the input widgets between the title and the buttons.
* ``build_value()`` — return the field value to dismiss with, or ``None`` to stay open (e.g.
  after showing an error via ``_set_error``).

``PREFIX`` gives the Apply/Cancel buttons stable ids (``{prefix}-apply`` / ``{prefix}-cancel``)
so a wizard's widgets are addressable, while the handlers key off the shared classes.
"""

from typing import Any, Iterable

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Static


class WizardScreen(ModalScreen[object]):
    """Base modal shell for field wizards. Dismisses with the field value, or None if cancelled."""

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel', priority=True),
    ]

    TITLE = ''
    PREFIX = 'wizard'

    DEFAULT_CSS = """
    WizardScreen { align: center middle; }
    WizardScreen .wizard-box {
        width: 60; height: auto; max-height: 90%; border: round $primary; padding: 1 2;
    }
    WizardScreen Static { height: 1; }
    WizardScreen RadioSet { height: auto; margin-bottom: 1; }
    WizardScreen .field-row { height: 3; width: 1fr; }
    WizardScreen .field-row Static { width: 12; content-align: left middle; height: 3; }
    WizardScreen .field-row Input { width: 1fr; }
    WizardScreen .wizard-result { color: $success; text-style: bold; margin-top: 1; }
    WizardScreen .wizard-error { color: $error; text-style: bold; }
    WizardScreen .wizard-buttons { height: 3; margin-top: 1; }
    WizardScreen .wizard-buttons Button {
        margin-right: 1; background: $surface; color: $text; border: round $primary;
    }
    WizardScreen .wizard-buttons Button:focus {
        background: $primary; color: $text; border: round $primary; text-style: bold;
    }
    """

    def compose(self):
        with Vertical(id=f'{self.PREFIX}-box', classes='wizard-box'):
            if self.TITLE:
                yield Static(self.TITLE)
            yield from self.compose_body()
            yield Static('', classes='wizard-error')
            with Horizontal(classes='wizard-buttons'):
                yield Button('Apply', id=f'{self.PREFIX}-apply', classes='wizard-apply')
                yield Button('Cancel', id=f'{self.PREFIX}-cancel', classes='wizard-cancel')

    def compose_body(self) -> Iterable[Widget]:
        """Yield the wizard's input widgets (override)."""
        return ()

    def build_value(self) -> Any:
        """Return the value to dismiss with, or None to stay open (override)."""
        raise NotImplementedError

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, '.wizard-cancel')
    def _cancel_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    @on(Button.Pressed, '.wizard-apply')
    def _apply_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        value = self.build_value()
        if value is not None:
            self.dismiss(value)

    def _set_error(self, text: str) -> None:
        self.query_one('.wizard-error', Static).update(text)
