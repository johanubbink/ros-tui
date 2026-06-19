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

"""The textual application: three tabs over one shared RosBridge."""

from textual.app import App
from textual.binding import Binding
from textual.containers import Center, Middle
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from ros_tui.ui.actions_tab import ActionsTab
from ros_tui.ui.interface_tab import InterfaceTab
from ros_tui.ui.messages import GraphUpdated
from ros_tui.ui.services_tab import ServicesTab
from ros_tui.ui.theme import ROS_DARK
from ros_tui.ui.topics_tab import TopicsTab

HELP_TEXT = """\
ros_tui — ROS 2 interface workbench

  ctrl+1 / ctrl+2 / ctrl+3   switch to Actions / Services / Topics
  ctrl+f                     focus the filter box of the current tab
  ctrl+s                     primary action: Send goal / Call / Publish once
  ctrl+k                     Cancel goal / Stop periodic publish
  ctrl+r                     reset the editor to the message defaults
  ctrl+l                     clear the output log of the current tab
  f1                         this help · esc closes it
  ctrl+q                     quit

Editor tips (the YAML dialect of `ros2 action send_goal` / `ros2 topic pub`):
  stamp: now                 builtin_interfaces/Time stamped at send time
  header: auto               empty Header with the stamp set at send time
  .nan / .inf / -.inf        float specials
  Values are validated against field types, ranges and array sizes before
  anything is sent; errors show the exact field path below the editor.
"""


class HelpScreen(ModalScreen):
    BINDINGS = [
        Binding('escape', 'dismiss_help', 'Close', priority=True),
        Binding('f1', 'dismiss_help', 'Close', show=False, priority=True),
    ]

    DEFAULT_CSS = """
    HelpScreen { align: center middle; background: $background 60%; }
    HelpScreen #help-dialog {
        width: 80; max-width: 95%; height: auto;
        background: $surface; border: round $primary; padding: 1 2;
        border-title-color: $primary; border-title-align: left;
    }
    """

    def compose(self):
        dialog = Static(HELP_TEXT, id='help-dialog')
        dialog.border_title = 'Help'
        with Middle(), Center():
            yield dialog

    def action_dismiss_help(self) -> None:
        self.dismiss()


class RosTuiApp(App):
    TITLE = 'ros_tui'
    SUB_TITLE = 'ROS 2 interface workbench'

    # All colour comes from the ros-dark theme variables (ros_tui/ui/theme.py); never
    # hardcode hex here. Spacing is on a {0,1,2}-cell scale. Borders have one resting
    # treatment ($surface-lighten-2) and one focus treatment ($primary) — the blue seam.
    # See docs/STYLE_GUIDE.md.
    CSS = """
    /* ── left column: the entity list ─────────────────────────────────────── */
    .entity-list { width: 32%; min-width: 18; border: round $surface-lighten-2; }
    .entity-list:focus-within { border: round $primary; }
    .entity-list #filter-input { border: none; height: 1; padding: 0 1; background: $surface; }
    .entity-list #entity-list { height: 1fr; border: none; background: $surface; padding: 0 1; }

    /* ── right column: detail · editor · error · controls · status · log ──── */
    .right-pane { width: 1fr; padding: 0 0 0 1; }
    #detail-line { height: 1; padding: 0 1; }
    #editor { height: 3fr; min-height: 5; border: round $surface-lighten-2; }
    #editor:focus { border: round $primary; }
    #editor-error {
        display: none; height: auto; max-height: 3; padding: 0 1;
        background: $error-muted; color: $text-error;
    }

    /* ── controls: a flat, outlined button system (no bevel; matches the round panes) ── */
    .controls { height: 3; padding: 0 1; }
    .controls Button {
        margin: 0 1 0 0; min-width: 10; height: 3;
        background: $surface; color: $text;
        border: round $surface-lighten-2; text-style: none;
    }
    .controls Button:hover { border: round $primary; color: $text-primary; }
    .controls Button:focus { border: round $primary; background: $primary 15%; text-style: none; }
    .controls Button:disabled { border: round $surface-lighten-1; color: $text-muted; }
    .controls Button.-active { background: $primary; color: $background; border: round $primary; }
    /* primary action (Send / Call / Publish): a blue-outlined call to action that fills on touch */
    .controls Button.-primary { color: $text-primary; border: round $primary; }
    .controls Button.-primary:hover { background: $primary; color: $background; }
    /* a running rate/echo/resume toggle reads as amber while it is live */
    .controls Button.running { color: $text-warning; border: round $warning; }
    .controls Button.running:hover { background: $warning; color: $background; }
    #rate-input { width: 10; height: 3; margin: 0 1 0 0; border: round $surface-lighten-2; }
    #rate-input:focus { border: round $primary; }

    /* ── status line: a calm, glyph-led 'what just happened' line (no heavy band) ── */
    .status-strip { height: 1; padding: 0 1; color: $text-muted; }

    #output-log { height: 2fr; min-height: 5; border: round $surface-lighten-2; padding: 0 1; }

    /* ── quiet, left-aligned border-title labels on each pane ─────────────── */
    .entity-list, #editor, #output-log {
        border-title-color: $text-muted; border-title-align: left;
        border-subtitle-color: $text-muted;
    }
    """

    BINDINGS = [
        Binding('ctrl+1', "switch_tab('actions')", 'Actions', show=False),
        Binding('ctrl+2', "switch_tab('services')", 'Services', show=False),
        Binding('ctrl+3', "switch_tab('topics')", 'Topics', show=False),
        Binding('ctrl+f', 'focus_filter', 'Filter', priority=True),
        Binding('ctrl+s', 'primary_action', 'Send/Call/Pub', priority=True),
        Binding('ctrl+k', 'secondary_action', 'Cancel/Stop', priority=True),
        Binding('ctrl+r', 'reset_editor', 'Reset msg', priority=True),
        Binding('ctrl+l', 'clear_log', 'Clear log', priority=True),
        Binding('f1', 'help', 'Help'),
    ]

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge

    def compose(self):
        yield Header()
        with TabbedContent(initial='actions'):
            with TabPane('Actions', id='actions'):
                yield ActionsTab(self._bridge, id='actions-tab')
            with TabPane('Services', id='services'):
                yield ServicesTab(self._bridge, id='services-tab')
            with TabPane('Topics', id='topics'):
                yield TopicsTab(self._bridge, id='topics-tab')
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(ROS_DARK)
        self.theme = 'ros-dark'
        self._bridge.set_graph_listener(lambda snapshot: self.post_message(GraphUpdated(snapshot)))
        self._apply_graph(self._bridge.latest_graph)

    def on_unmount(self) -> None:
        self._bridge.set_graph_listener(None)

    def on_graph_updated(self, message: GraphUpdated) -> None:
        message.stop()
        self._apply_graph(message.snapshot)

    def _apply_graph(self, snapshot) -> None:
        self.query_one('#actions-tab', ActionsTab).set_entries(snapshot.actions)
        self.query_one('#services-tab', ServicesTab).set_entries(snapshot.services)
        self.query_one('#topics-tab', TopicsTab).set_entries(snapshot.topics)

    def _active_tab(self) -> InterfaceTab | None:
        tabbed = self.query_one(TabbedContent)
        if not tabbed.active:
            return None
        return tabbed.get_pane(tabbed.active).query(InterfaceTab).first()

    def action_switch_tab(self, pane_id: str) -> None:
        self.query_one(TabbedContent).active = pane_id

    def action_focus_filter(self) -> None:
        tab = self._active_tab()
        if tab is not None:
            tab.focus_filter()

    def action_primary_action(self) -> None:
        tab = self._active_tab()
        if tab is not None:
            tab.primary_action()

    def action_secondary_action(self) -> None:
        tab = self._active_tab()
        if tab is not None:
            tab.secondary_action()

    def action_reset_editor(self) -> None:
        tab = self._active_tab()
        if tab is not None:
            tab.reset_editor()

    def action_clear_log(self) -> None:
        tab = self._active_tab()
        if tab is not None:
            tab.clear_log()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
