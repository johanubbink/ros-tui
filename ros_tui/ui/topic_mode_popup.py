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

"""Modal asking whether to work with a topic in publish or subscribe mode."""

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ros_tui.ros.graph import InterfaceEntry
from ros_tui.ui.messages import TopicCountsReady


def _accel(label: str) -> Text:
    """Label with its first letter bold+underlined to advertise the keyboard shortcut."""
    text = Text(label)
    text.stylize('bold underline', 0, 1)
    return text


class TopicModePopup(ModalScreen[str | None]):
    """Dismisses with 'publish', 'subscribe', or None (cancelled)."""

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel', priority=True),
        Binding('left', 'focus_publish', 'Focus publish', show=False),
        Binding('right', 'focus_subscribe', 'Focus subscribe', show=False),
        Binding('p', 'choose_publish', 'Publish', show=False),
        Binding('s', 'choose_subscribe', 'Subscribe', show=False),
    ]

    DEFAULT_CSS = """
    TopicModePopup { align: center middle; }
    TopicModePopup #topic-mode-box { width: 60; height: auto; border: round $primary; padding: 1 2; }
    TopicModePopup #topic-mode-box Static { height: 1; }
    TopicModePopup #topic-mode-buttons { height: 3; margin-top: 1; }
    TopicModePopup #topic-mode-buttons Button {
        margin-right: 1;
        background: $surface;
        color: $text;
        border: round $primary;
    }
    TopicModePopup #topic-mode-buttons Button:focus {
        background: $primary;
        color: $text;
        border: round $primary;
        text-style: bold;
    }
    """

    def __init__(self, entry: InterfaceEntry, counts_future):
        super().__init__()
        self._entry = entry
        self._counts_future = counts_future

    def compose(self):
        with Vertical(id='topic-mode-box'):
            yield Static(f'Topic: {self._entry.name}', id='topic-mode-name')
            yield Static(self._entry.types[0] if self._entry.types else '', id='topic-mode-type')
            yield Static('publishers: … · subscribers: …', id='topic-mode-counts')
            with Horizontal(id='topic-mode-buttons'):
                yield Button(_accel('Publish'), id='topic-mode-publish')
                yield Button(_accel('Subscribe'), id='topic-mode-subscribe')

    def on_mount(self) -> None:
        self._counts_future.add_done_callback(self._post_counts)
        self.query_one('#topic-mode-publish', Button).focus()

    def _post_counts(self, done) -> None:
        try:
            pubs, subs = done.result()
            self.post_message(TopicCountsReady(pubs, subs, None))
        except BaseException as error:  # noqa: BLE001 - shown as '?' in the popup
            self.post_message(TopicCountsReady(None, None, str(error) or type(error).__name__))

    def on_topic_counts_ready(self, message: TopicCountsReady) -> None:
        message.stop()
        if message.error is None:
            text = f'publishers: {message.pub_count} · subscribers: {message.sub_count}'
        else:
            text = f'endpoint counts unavailable: {message.error}'
        self.query_one('#topic-mode-counts', Static).update(text)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_publish(self) -> None:
        self.query_one('#topic-mode-publish', Button).focus()

    def action_focus_subscribe(self) -> None:
        self.query_one('#topic-mode-subscribe', Button).focus()

    def action_choose_publish(self) -> None:
        self.dismiss('publish')

    def action_choose_subscribe(self) -> None:
        self.dismiss('subscribe')

    @on(Button.Pressed, '#topic-mode-publish')
    def _publish_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss('publish')

    @on(Button.Pressed, '#topic-mode-subscribe')
    def _subscribe_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss('subscribe')
