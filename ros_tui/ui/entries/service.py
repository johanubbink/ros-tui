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

Pure Python (no textual, no rclpy).
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
from ros_tui.ui.entries.base import Area, Context, Tab, Verb
from ros_tui.ui.entries.message import EDITOR, MessageEntry
from ros_tui.ui.fields import FieldRows, summary
from ros_tui.ui.nav import NavState


@dataclass
class Call:
    """One call of a service: running until `done`, then OK or failed with `error`."""

    at: float  # Clock time it was sent.
    request: str  # The request, summarised.
    done: bool = False
    elapsed_ms: float = 0.0
    error: str = ''


class ServiceEntry(MessageEntry):
    """A service: its REQUEST editor and the RESPONSE of the last call."""

    KIND = 'srv'
    ROLE = 'request'
    AREAS = (Area(EDITOR, 'REQUEST', 'edit', True, folds=True, helpers=True), Area('out', 'RESPONSE', folds=True))

    def __init__(self, tab: Tab, ctx: Context | None = None):
        super().__init__(tab, ctx)
        self.call: Call | None = None  # The last call.
        self.response: FieldRows | None = None  # The rows of the last response.

    def load_extra(self, interface: type) -> Any:
        """The response's structure, loaded with the request's."""
        return class_structure(interface.Response)

    def form(self, area: Area | None) -> FieldRows | None:
        if area is not None and area.id == 'out':
            return self.response
        return super().form(area)

    def verbs(self) -> dict[str, Verb]:
        return {**super().verbs(), 'primary': lambda nav, how, _: self._call(nav, how)}

    def _call(self, nav: NavState, how: str) -> None:
        """space / ^s: check the request, then call the service with it."""
        tab = self.tab
        if self.call is not None and not self.call.done:
            nav.feedback.refuse(how, f'still calling {tab.name} — wait for the response', 'a call is still running')
            return
        ready = self._send(nav, how, '▶ called', 'c', f'calling {tab.name}')
        if ready is None:
            return
        request, time_setters, sent = ready
        call = self.call = Call(nav.feedback.clock(), sent)
        self.response = None
        future = self._bridge.call_service(tab.name, self.type, request, time_setters)
        future.add_done_callback(lambda done: self._answered(nav, call, done))

    def _answered(self, nav: NavState, call: Call, future: Any) -> None:
        """On the bridge's thread: time the answer, make it plain data, then apply it on the UI thread."""
        elapsed_ms = (nav.feedback.clock() - call.at) * 1000.0
        try:
            plain, error = message_to_plain(future.result()), ''
        except BaseException as failure:  # noqa: BLE001 - a failed call is shown, not raised
            plain, error = None, str(failure) or type(failure).__name__
        self._post(lambda: self._call_done(nav, call, elapsed_ms, plain, error))

    def _call_done(self, nav: NavState, call: Call, elapsed_ms: float, plain: dict | None, error: str) -> None:
        call.done, call.elapsed_ms, call.error = True, elapsed_ms, error
        timing = f'{elapsed_ms:.1f} ms'
        if error:
            nav.feedback.add_activity(self.tab, f'✗ call failed: {error} ({timing})', 'r')
            return
        self.response = FieldRows(self.extra or (), plain, editable=False)
        text = summary(plain, SUMMARY_MAX_CHARS)
        nav.feedback.add_activity(self.tab, f'✓ response · {text} ({timing})' if text else f'✓ response ({timing})', 'g')
