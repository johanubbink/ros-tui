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
from textual.widgets import Button, Static

from ros_tui.ros.message_yaml import to_truncated_yaml
from ros_tui.ui import styles
from ros_tui.ui.interface_tab import InterfaceTab
from ros_tui.ui.messages import ServiceCompleted


class ServicesTab(InterfaceTab):
    kind = 'srv'
    list_placeholder = 'filter services…'
    list_title = 'Services'
    status_id = 'service-status'

    def __init__(self, bridge, **kwargs):
        super().__init__(bridge, **kwargs)
        self._call_in_flight = False

    def compose_controls(self):
        yield Button('Call', id='call-button', variant='primary')

    def compose_status(self):
        yield Static(id='service-status', classes='status-strip')

    def on_mount(self) -> None:
        self._set_status('no call yet', 'idle')

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
        self.write_log(styles.info(f'{styles.GLYPH_REQUEST} {name}'))
        self._set_status(f'CALLING  {name}', 'busy')
        self.query_one('#call-button', Button).disabled = True
        started = time.monotonic()
        future = self._bridge.call_service(name, type_name, request, time_setters)

        def on_done(done_future) -> None:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            try:
                response = done_future.result()
                self.post_message(ServiceCompleted(name, response, None, elapsed_ms))
            except BaseException as error:  # noqa: BLE001 - rendered in the log
                text = str(error) or type(error).__name__
                self.post_message(ServiceCompleted(name, None, text, elapsed_ms))

        future.add_done_callback(on_done)

    def on_service_completed(self, message: ServiceCompleted) -> None:
        message.stop()
        self._call_in_flight = False
        self.query_one('#call-button', Button).disabled = False
        if message.error is not None:
            self.write_log(
                styles.fail(f'{styles.GLYPH_FAIL} {message.service_name}: {message.error}')
            )
            self._set_status(f'{message.service_name} failed', 'fail')
            return
        self.write_log(
            styles.ok(f'{styles.GLYPH_RESPONSE} {message.service_name} '
                      f'response in {message.elapsed_ms:.1f} ms')
        )
        self._set_status(f'responded in {message.elapsed_ms:.0f} ms', 'ok')
        self.write_log(to_truncated_yaml(message.response))
