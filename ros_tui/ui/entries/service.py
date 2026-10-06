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

"""The service entry: a REQUEST editor in field rows, and the RESPONSE of the last call.

Pure Python (no textual, no rclpy), as the design's services branches of send() and renderEntry.
space / ^s checks the request and calls the service (`call_service`); the RESPONSE title shows
"calling…" until the answer, then "✓ OK" and how long it took on the bridge's clock, or "✗ failed"
with the reason as an errline. Each call and answer is an activity line ("▶ called · a: 19, b: 23",
"✓ response · sum: 42 (50.0 ms)"). One call runs at a time per service. Editing, history and undo
come from `MessageEntry`.
"""

from dataclasses import dataclass
from typing import Any

from ros_tui.constants import SUMMARY_MAX_CHARS
from ros_tui.ros.message_yaml import class_structure, message_to_plain
from ros_tui.ui.entries.message import MessageData, MessageEntry
from ros_tui.ui.fields import FieldRows, summary
from ros_tui.ui.nav import Area, NavState, Tab


@dataclass
class Call:
    """One call of a service: running until `done`, then OK or failed with `error`."""

    at: float  # Clock time it was sent.
    request: str  # The request, summarised.
    done: bool = False
    elapsed_ms: float = 0.0
    error: str = ''


@dataclass
class ServiceData(MessageData):
    call: Call | None = None  # The last call.
    response: FieldRows | None = None  # The rows of the last response.


class ServiceEntry(MessageEntry):
    """The service entry kind."""

    KIND = 'srv'

    def new_data(self) -> ServiceData:
        return ServiceData()

    def load_extra(self, interface: type) -> Any:
        """The response's structure, loaded with the request's."""
        return class_structure(interface.Response)

    def form(self, tab: Tab, area: Area | None) -> FieldRows | None:
        if area is not None and area.id == 'out':
            return self.data(tab).response
        return super().form(tab, area)

    def verb(self, nav: NavState, tab: Tab | None, name: str, how: str, arg: Any = None) -> bool:
        if name == 'primary':
            self.call(nav, tab, how)
            return True
        return super().verb(nav, tab, name, how, arg)

    def call(self, nav: NavState, tab: Tab, how: str) -> None:
        """space / ^s: check the request, then call the service with it."""
        data = self.data(tab)
        if data.call is not None and not data.call.done:
            nav.show_toast(f'still calling {tab.name} — wait for the response', 'bad')
            nav.log_line(how, 'a call is still running')
            return
        built = self.checked(nav, tab, how)
        if built is None:
            return
        request, time_setters = built
        call = data.call = Call(nav.clock(), summary(self.remember(tab), SUMMARY_MAX_CHARS))
        data.response = None
        nav.errlines.pop(tab.key, None)
        nav.add_activity(tab, f'▶ called · {call.request}' if call.request else '▶ called', 'c')
        nav.log_line(how, f'calling {tab.name}')
        future = self._bridge.call_service(tab.name, data.type, request, tuple(time_setters))
        future.add_done_callback(lambda done: self._answered(nav, tab, call, done))

    def _answered(self, nav: NavState, tab: Tab, call: Call, future: Any) -> None:
        """On the bridge's thread: time the answer, make it plain data, then apply it on the UI thread."""
        elapsed_ms = (nav.clock() - call.at) * 1000.0
        try:
            plain, error = message_to_plain(future.result()), ''
        except BaseException as failure:  # noqa: BLE001 - a failed call is shown, not raised
            plain, error = None, str(failure) or type(failure).__name__
        self._post(lambda: self._call_done(nav, tab, call, elapsed_ms, plain, error))

    def _call_done(self, nav: NavState, tab: Tab, call: Call, elapsed_ms: float, plain: dict | None,
                   error: str) -> None:
        call.done, call.elapsed_ms, call.error = True, elapsed_ms, error
        timing = f'{elapsed_ms:.1f} ms'
        if error:
            nav.add_activity(tab, f'✗ call failed: {error} ({timing})', 'r')
            return
        data = self.data(tab)
        data.response = FieldRows(data.extra or (), plain, editable=False)
        text = summary(plain, SUMMARY_MAX_CHARS)
        nav.add_activity(tab, f'✓ response · {text} ({timing})' if text else f'✓ response ({timing})', 'g')
