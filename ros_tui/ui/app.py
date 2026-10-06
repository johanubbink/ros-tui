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
every key reaches the keymap. ctrl+q and ctrl+c quit, as `:q` does.

Graph updates feed the ☰ list. A GraphSnapshot has no publisher counts, so on each graph change
the app asks the bridge for every topic's counts and folds the answers into the list in one go.
Until a topic's count arrives it counts as unpublished (it would open in Publish, not Echo).

The entries are `entries.entry_router` over the bridge. An entry's bridge answers arrive on the
bridge's thread; the router's `post` wraps each in a `UiCall` message, so it is applied on the UI
thread, and the views redraw after it. Its `work` (importing a message type) runs in a textual
thread worker and posts its result the same way.

The overlays (search, :log, the command suggestions, which-key, the field helper, the toast) are
`Overlay` views on the `overlay` layer; each says where it goes and `refresh_views` places it.
Search and :log veil what is under them by dimming it. The model's clock is the bridge's `now()`;
a UI_TICK_PERIOD_S timer calls `tick()`, which lets the entries take in their echoes and the model
expire the toast.
"""

from textual import events
from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen

from ros_tui.constants import UI_TICK_PERIOD_S
from ros_tui.ros.graph import GraphSnapshot
from ros_tui.ui import theme
from ros_tui.ui.entries import entry_router
from ros_tui.ui.messages import GraphUpdated, PublisherCount, UiCall
from ros_tui.ui.nav import NavState
from ros_tui.ui.widgets import (ActivityStrip, CommandSuggestions, EntryBody, EntryTabRow, Footer, HelperPopup,
                                HomeList, LogPopup, SearchPopup, ToastView, TopBar, WhichKeyPopup)
from ros_tui.ui.widgets.base import NavView, Overlay


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
    /* The veil under search and :log (the design's rgba(0,0,0,.5)): dim all but the footer. */
    Screen.-veiled TopBar, Screen.-veiled EntryTabRow, Screen.-veiled #body, Screen.-veiled ActivityStrip {
        opacity: 50%;
    }
    """

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge
        self.nav = NavState(entry_router(bridge, lambda fn: self.post_message(UiCall(fn)), self._work),
                            clock=bridge.now, wall=bridge.time_of_day)
        self._graph: GraphSnapshot | None = None
        self._publishers: dict[str, int] = {}
        self._publishers_dirty = False

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
        self.set_interval(UI_TICK_PERIOD_S, self.tick)

    def on_unmount(self) -> None:
        self._bridge.set_graph_listener(None)

    # ---------- keys ----------
    def on_key(self, event: events.Key) -> None:
        event.stop()
        event.prevent_default()
        self.nav.handle_key(event.key)
        if self.nav.quit:
            self.exit()
            return
        self.refresh_views()

    def on_resize(self, event: events.Resize) -> None:
        self.refresh_views()

    def tick(self) -> None:
        """The clock tick: redraw when the model expired something. The harness calls it after
        each `advance()`, so a toast's expiry follows the simulated clock."""
        if self.nav.tick():
            self.refresh_views()

    def refresh_views(self) -> None:
        nav = self.nav
        home = nav.tab is None
        self.query_one(HomeList).display = home
        self.query_one(EntryBody).display = not home
        self.screen.set_class(bool(nav.search or nav.logv), '-veiled')
        for overlay in self.query(Overlay):
            spot = overlay.place(*overlay.parent.content_size)
            overlay.display = spot is not None
            if spot:
                x, y, width, height = spot
                overlay.styles.offset = (x, y)
                overlay.styles.width = width
                overlay.styles.height = height
        for view in self.query(NavView):
            view.refresh(layout=True)

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
        self._graph = snapshot
        self.nav.set_catalog(snapshot, self._publishers)
        self.refresh_views()
        for topic in snapshot.topics:
            future = self._bridge.topic_endpoint_counts(topic.name)
            future.add_done_callback(lambda done, name=topic.name: self._counts_done(name, done))

    def _counts_done(self, name: str, future) -> None:
        """On the bridge's thread: pass the publisher count on (a failed count changes nothing)."""
        if not future.cancelled() and future.exception() is None:
            self.post_message(PublisherCount(name, future.result()[0]))

    def on_publisher_count(self, message: PublisherCount) -> None:
        message.stop()
        if self._publishers.get(message.topic_name) == message.count:
            return
        self._publishers[message.topic_name] = message.count
        if not self._publishers_dirty:  # One catalogue rebuild for a burst of counts, not one each.
            self._publishers_dirty = True
            self.call_later(self._apply_publishers)

    def _apply_publishers(self) -> None:
        self._publishers_dirty = False
        self.nav.set_catalog(self._graph, self._publishers)
        self.refresh_views()
