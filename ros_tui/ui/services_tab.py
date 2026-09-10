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

"""Services tab: fill a request, call, see the response and round-trip time."""

import time

from textual import on
from textual.widgets import Button, Static, TextArea

from ros_tui.ros.message_yaml import to_truncated_yaml
from ros_tui.ui.interface_tab import InterfaceTab
from ros_tui.ui.messages import ServiceCompleted


class ServicesTab(InterfaceTab):
    kind = 'srv'
    list_placeholder = 'filter services…'
    entity_label = 'Service'

    def __init__(self, bridge, **kwargs):
        super().__init__(bridge, **kwargs)
        self._call_in_flight = False

    def compose_controls(self):
        yield Button('Call', id='call-button', variant='primary')
        yield Static('', classes='controls-spacer')
        yield Button('Fill…', id='wizard-button', tooltip='fill the field on the cursor line')

    @on(Button.Pressed, '#wizard-button')
    def _on_wizard_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.wizard_action()

    def on_selection_changed(self) -> None:
        # Land in the editor so the request is ready to edit and call straight after
        # picking a service — the whole point of selecting one here is to call it.
        self.query_one('#editor', TextArea).focus()

    @on(Button.Pressed, '#call-button')
    def _on_call_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.primary_action()

    def primary_action(self) -> None:
        if self._call_in_flight:
            return  # ctrl+s bypasses the disabled button; enforce single flight here too.
        built = self.build_from_editor()
        if built is None:
            return
        self._call_in_flight = True
        request, time_setters = built
        name, type_name = self._current.name, self._current.types[0]
        self.write_log(f'→ {name}', style='bold cyan')
        self.query_one('#call-button', Button).disabled = True
        started = time.monotonic()
        future = self._bridge.call_service(name, type_name, request, time_setters)

        def on_done(done_future) -> None:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            try:
                response = done_future.result()
                self.post_message(ServiceCompleted(name, response, None, elapsed_ms))
            except BaseException as error:  # noqa: BLE001 - rendered in the log
                self.post_message(
                    ServiceCompleted(name, None, self._error_text(error), elapsed_ms)
                )

        future.add_done_callback(on_done)

    def on_service_completed(self, message: ServiceCompleted) -> None:
        message.stop()
        self._call_in_flight = False
        self.query_one('#call-button', Button).disabled = False
        if message.error is not None:
            self.write_log(f'✗ {message.service_name}: {message.error}', style='bold red')
            return
        self.write_log(
            f'← {message.service_name} response in {message.elapsed_ms:.1f} ms',
            style='bold green',
        )
        self.write_log(to_truncated_yaml(message.response))
