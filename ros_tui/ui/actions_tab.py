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

"""Actions tab: send a goal, watch status/feedback stream, see the result, cancel."""

import time
from collections import deque

from textual import on
from textual.widgets import Button, Static

from ros_tui.constants import (
    ECHO_RENDER_PERIOD_S,
    FEEDBACK_BUFFER_MAXLEN,
    FEEDBACK_MAX_RENDER_PER_TICK,
)
from ros_tui.ros.events import ActionEventKind, goal_status_name
from ros_tui.ros.message_yaml import to_truncated_yaml
from ros_tui.ui import styles
from ros_tui.ui.interface_tab import InterfaceTab
from ros_tui.ui.messages import ActionEventMessage

# Terminal goal status -> semantic role. In-flight states default to 'busy'/'info'.
_OUTCOME = {
    'SUCCEEDED': 'ok',
    'ABORTED': 'fail',
    'REJECTED': 'fail',
    'ERROR': 'fail',
    'CANCELED': 'warn',
}


class ActionsTab(InterfaceTab):
    kind = 'action'
    list_placeholder = 'filter actions…'
    list_title = 'Actions'
    status_id = 'goal-status'

    def __init__(self, bridge, **kwargs):
        super().__init__(bridge, **kwargs)
        self._goal_action_name: str | None = None
        self._goal_started = 0.0
        self._feedback: deque = deque(maxlen=FEEDBACK_BUFFER_MAXLEN)

    def compose_controls(self):
        yield Button('Send goal', id='send-button', variant='primary')
        yield Button('Cancel', id='cancel-button', disabled=True)

    def compose_status(self):
        yield Static(id='goal-status', classes='status-strip')

    def on_mount(self) -> None:
        self._set_status('no goal sent yet', 'idle')
        self.set_interval(ECHO_RENDER_PERIOD_S, self._drain_feedback)

    @on(Button.Pressed, '#send-button')
    def _on_send_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.primary_action()

    @on(Button.Pressed, '#cancel-button')
    def _on_cancel_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.secondary_action()

    def primary_action(self) -> None:
        if self._goal_action_name is not None:
            self.write_log(
                styles.fail(f'{styles.GLYPH_FAIL} a goal on {self._goal_action_name} '
                            'is still in flight')
            )
            return
        built = self.build_from_editor()
        if built is None:
            return
        goal, time_setters = built
        name, type_name = self._current.name, self._current.types[0]
        self._goal_action_name = name
        self._goal_started = time.monotonic()
        self._feedback.clear()
        self._set_status(f'SENDING  {name}', 'busy')
        self.query_one('#send-button', Button).disabled = True
        self.query_one('#cancel-button', Button).disabled = False
        self.write_log(styles.info(f'{styles.GLYPH_REQUEST} goal sent to {name}'))
        self._bridge.send_goal(
            name,
            type_name,
            goal,
            on_event=lambda event: self.post_message(ActionEventMessage(event)),
            time_setters=time_setters,
        )

    def secondary_action(self) -> None:
        if self._goal_action_name is None:
            return
        self._set_status(f'CANCELING  {self._goal_action_name}', 'warn')
        self._bridge.cancel_goal(self._goal_action_name)

    def on_action_event_message(self, message: ActionEventMessage) -> None:
        message.stop()
        event = message.event
        if event.action_name != self._goal_action_name:
            return  # Stale event from a goal we already finished reporting.
        kind = event.kind
        if kind == ActionEventKind.ACCEPTED:
            self._set_status(f'EXECUTING  {event.action_name}', 'busy')
        elif kind == ActionEventKind.FEEDBACK:
            self._feedback.append(event.payload)
        elif kind == ActionEventKind.REJECTED:
            self.write_log(styles.fail(f'{styles.GLYPH_FAIL} goal rejected by the server'))
            self._finish_goal('REJECTED')
        elif kind == ActionEventKind.ERROR:
            self.write_log(styles.fail(f'{styles.GLYPH_FAIL} {event.payload}'))
            self._finish_goal('ERROR')
        elif kind == ActionEventKind.CANCEL_ACCEPTED:
            self.write_log(styles.warn('cancel request accepted'))
        elif kind == ActionEventKind.CANCEL_REJECTED:
            self.write_log(styles.fail('cancel request rejected'))
        elif kind == ActionEventKind.RESULT:
            self._drain_feedback()
            status = goal_status_name(event.status)
            elapsed = time.monotonic() - self._goal_started
            self.write_log(
                styles.styled(f'— result: {status} in {elapsed:.2f} s —',
                              _OUTCOME.get(status, 'info'))
            )
            self.write_log(to_truncated_yaml(event.payload))
            self._finish_goal(status)

    def _finish_goal(self, status: str) -> None:
        # A finished goal is never "in flight"; an unmapped terminal status is a warning,
        # not the blue ▸ busy glyph.
        self._set_status(f'{status}  {self._goal_action_name}', _OUTCOME.get(status, 'warn'))
        self._goal_action_name = None
        self.query_one('#send-button', Button).disabled = False
        self.query_one('#cancel-button', Button).disabled = True

    def _drain_feedback(self) -> None:
        if not self._feedback:
            return
        pending = list(self._feedback)
        self._feedback.clear()
        if len(pending) > FEEDBACK_MAX_RENDER_PER_TICK:
            hidden = len(pending) - FEEDBACK_MAX_RENDER_PER_TICK
            self.write_log(styles.muted(f'(+{hidden} feedback messages coalesced)'))
            pending = pending[-FEEDBACK_MAX_RENDER_PER_TICK:]
        for payload in pending:
            self.write_log(styles.feedback('feedback:'))
            self.write_log(to_truncated_yaml(payload))
