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

"""The textual application: one screen over the nav model (`NavState`) and a shared bridge.

One `on_key` hands every key to `NavState.handle_key`, then redraws the views from the model.
Nothing takes focus and textual's own bindings (focus cycling, the ctrl+p palette) are off, so
every key reaches the keymap. ctrl+q and ctrl+c quit, as `:q` does. One `on_click` hands every
left click to `NavState.click`, with the target the view drew under the mouse.

Graph updates feed the ☰ list; a GraphSnapshot carries each topic's publisher and subscriber counts.

The entries are made by `entries.kinds.entry_factory` over the bridge. An entry's bridge answers
arrive on the bridge's thread; its `post` wraps each in a `UiCall` message, so it is applied on the
UI thread, and the views redraw after it. Its `work` (importing a message type) runs in a textual
thread worker and posts its result the same way.

The overlays (search, :log, the command suggestions, which-key, the field helper, the toast) are
`Overlay` views on the `overlay` layer; each says where it goes and `refresh_views` places it.
Search and :log veil what is under them by dimming it. The model's clock is the bridge's `now()`;
a UI_TICK_PERIOD_S timer calls `tick()`, which lets the entries take in their echoes and the model
expire the toast.
"""

from typing import Callable

from textual import events
from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import Screen

from ros_tui.constants import UI_TICK_PERIOD_S
from ros_tui.ros.graph import GraphSnapshot
from ros_tui.ui import theme
from ros_tui.ui.entries.kinds import entry_factory
from ros_tui.ui.feedback import Feedback
from ros_tui.ui.nav import LogView, NavState, Search
from ros_tui.ui.widgets import (ActivityStrip, CommandSuggestions, EntryBody, EntryTabRow, Footer, HelperPopup,
                                HomeList, LogPopup, SearchPopup, ToastView, TopBar, WhichKeyPopup)
from ros_tui.ui.widgets.base import NavView, Overlay


# Textual messages from the ROS thread to the UI thread: `post_message` is the only channel the
# bridge's callbacks may use.
class GraphUpdated(Message):
    def __init__(self, snapshot: GraphSnapshot):
        super().__init__()
        self.snapshot = snapshot


class UiCall(Message):
    """A bridge answer for an entry: `fn` runs on the UI thread, then the views redraw."""

    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self.fn = fn


class KeylessScreen(Screen, inherit_bindings=False):
    """The default screen without textual's tab / shift+tab focus cycling and ctrl+c copy."""


class Body(Vertical):
    """The body, which the toast and the helper popup are placed in: when it changes size (the
    activity strip grows a line), they are placed again, or the toast would sit below its bottom."""

    def on_resize(self, event: events.Resize) -> None:
        self.app.refresh_views()


class RosTuiApp(App, inherit_bindings=False):
    TITLE = 'ros_tui'
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding('ctrl+q', 'quit', show=False, priority=True),
        Binding('ctrl+c', 'quit', show=False, priority=True),
    ]
    CSS = """
    Screen { background: $rt-term; color: $rt-text; layers: default overlay; }
    #body { height: 1fr; padding: 0 1; layers: default overlay; }
    /* The veil under search and :log: dim all but the footer. */
    Screen.-veiled TopBar, Screen.-veiled EntryTabRow, Screen.-veiled #body, Screen.-veiled ActivityStrip {
        opacity: 50%;
    }
    """

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge
        self.nav = NavState(entry_factory(bridge, lambda fn: self.post_message(UiCall(fn)), self._work),
                            Feedback(bridge.now, bridge.time_of_day))

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **theme.css_variables()}

    def get_default_screen(self) -> Screen:
        return KeylessScreen(id='_default')

    def compose(self):
        nav = self.nav
        yield TopBar(nav)
        yield EntryTabRow(nav)
        with Body(id='body'):
            yield HomeList(nav)
            yield EntryBody(nav)
            yield HelperPopup(nav)
            yield ToastView(nav)
        yield ActivityStrip(nav)
        yield Footer(nav)
        # Overlays, bottom to top.
        yield SearchPopup(nav)
        yield LogPopup(nav)
        yield CommandSuggestions(nav)
        yield WhichKeyPopup(nav)

    def on_mount(self) -> None:
        self._bridge.set_graph_listener(lambda snapshot: self.post_message(GraphUpdated(snapshot)))
        self._apply_graph(self._bridge.latest_graph)
        self.ticker = self.set_interval(UI_TICK_PERIOD_S, self.tick)  # The harness pauses it on a simulated clock.

    def on_unmount(self) -> None:
        self._bridge.set_graph_listener(None)

    # ---------- keys ----------
    def on_key(self, event: events.Key) -> None:
        event.stop()
        event.prevent_default()
        # A symbol goes in as the character it types: textual names some after their unicode name
        # ('question_mark') but renames others ('slash'), and the character is the same for all.
        symbol = len(event.key) > 1 and '+' not in event.key and event.is_printable
        self.nav.handle_key(event.character if symbol else event.key)
        if self.nav.quit:
            self.exit()
            return
        self.refresh_views()

    # ---------- the mouse ----------
    def on_click(self, event: events.Click) -> None:
        """A click on no view (the body's padding): it only closes a popup."""
        event.stop()
        self.click(event)

    def click(self, event: events.Click, on_popup: bool = False) -> None:
        """A left click, from the view under the mouse (NavView.on_click): the views tag what they
        draw with what a click on it does (the `click` meta of `widgets.base.clickable`); the model
        does it (NavState.click), then the views redraw."""
        if event.button != 1:
            return
        self.nav.click(event.style.meta.get('click'), on_popup)
        self.refresh_views()

    def on_resize(self, event: events.Resize) -> None:
        self.refresh_views()

    def tick(self) -> None:
        """The clock tick: redraw when the model expired something. The harness calls it after
        each `advance()`, so a toast's expiry follows the simulated clock."""
        changed = self.nav.tick()
        if changed == 'all':
            self.refresh_views()
        elif changed:  # Only what the entries show (an echo, a goal's spinner): nothing moves or resizes.
            for view in self.query(NavView):
                if view.display:
                    view.refresh()

    def refresh_views(self) -> None:
        nav = self.nav
        home = nav.tab is None
        shows = {self.query_one(HomeList): home, self.query_one(EntryBody): not home}
        self.screen.set_class(isinstance(nav.overlay, (Search, LogView)), '-veiled')
        for overlay in self.query(Overlay):
            spot = overlay.place(*overlay.parent.content_size)
            shows[overlay] = spot is not None
            if spot:
                x, y, width, height = spot
                overlay.styles.offset = (x, y)
                overlay.styles.width = width
                overlay.styles.height = height
        # Lay the screen out again only when a view shows or hides, a popup shows (it may have moved
        # or grown) or the activity strip's height follows its lines; else just redraw what shows.
        strip = self.query_one(ActivityStrip)
        layout = (any(view.display != on for view, on in shows.items())
                  or any(on for view, on in shows.items() if isinstance(view, Overlay))
                  or strip.size.height != strip.wanted_height())
        for view, on in shows.items():
            view.display = on
        for view in self.query(NavView):
            if view.display:
                view.refresh(layout=layout)

    def _work(self, fn) -> None:
        """Run an entry's slow work (importing a message type) in a worker thread; it posts its result."""
        self.run_worker(fn, thread=True, group='entries', exit_on_error=False)

    def on_ui_call(self, message: UiCall) -> None:
        """A bridge answer for an entry (posted from the bridge's thread): apply it, then redraw."""
        message.stop()
        message.fn()
        self.refresh_views()

    # ---------- the graph ----------
    def on_graph_updated(self, message: GraphUpdated) -> None:
        message.stop()
        self._apply_graph(message.snapshot)

    def _apply_graph(self, snapshot: GraphSnapshot) -> None:
        self.nav.set_catalog(snapshot)
        self.refresh_views()
