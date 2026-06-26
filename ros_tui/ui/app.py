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
from ros_tui.ui.params_tab import ParamsTab
from ros_tui.ui.services_tab import ServicesTab
from ros_tui.ui.topics_tab import TopicsTab

HELP_TEXT = """\
ros_tui — ROS 2 interface workbench

  ctrl+1 / ctrl+2 / ctrl+3 / ctrl+4   switch to Actions / Services / Topics / Params
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
    HelpScreen { align: center middle; }
    HelpScreen Static { width: 80; max-width: 95%; border: round $primary; padding: 1 2; }
    """

    def compose(self):
        with Middle(), Center():
            yield Static(HELP_TEXT)

    def action_dismiss_help(self) -> None:
        self.dismiss()


class RosTuiApp(App):
    TITLE = 'ros_tui'
    SUB_TITLE = 'ROS 2 interface workbench'

    CSS = """
    .entity-list { width: 32%; min-width: 28; border: round $primary; }
    .entity-list #filter-input { border: none; height: 1; padding: 0 1; }
    .entity-list #entity-list { height: 1fr; border: none; }
    .right-pane { width: 1fr; padding: 0 1; }
    #detail-line { height: 1; }
    #editor { height: 3fr; min-height: 5; border: round $surface-lighten-2; }
    #editor-error { display: none; height: auto; max-height: 3; }
    .controls { height: 3; }
    .controls Button { margin-right: 1; min-width: 8; }
    #rate-input { width: 9; }
    #goal-status, #topics-status { height: 1; }
    #output-log { height: 2fr; min-height: 5; border: round $surface-lighten-2; }
    #params-node-label { height: 1; }
    #params-table { height: 3fr; min-height: 5; border: round $surface-lighten-2; }
    #value-input { height: 3; }
    #params-error { display: none; height: auto; max-height: 3; color: $error; }
    #params-log { height: 1fr; min-height: 4; border: round $surface-lighten-2; }
    """

    BINDINGS = [
        Binding('ctrl+1', "switch_tab('actions')", 'Actions', show=False),
        Binding('ctrl+2', "switch_tab('services')", 'Services', show=False),
        Binding('ctrl+3', "switch_tab('topics')", 'Topics', show=False),
        Binding('ctrl+4', "switch_tab('params')", 'Params', show=False),
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
            with TabPane('Params', id='params'):
                yield ParamsTab(self._bridge, id='params-tab')
        yield Footer()

    def on_mount(self) -> None:
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
        self.query_one('#params-tab', ParamsTab).set_entries(snapshot.nodes)

    def _active_tab(self):
        tabbed = self.query_one(TabbedContent)
        if not tabbed.active:
            return None
        pane = tabbed.get_pane(tabbed.active)
        # Try InterfaceTab subclasses first, then ParamsTab.
        matches = list(pane.query(InterfaceTab))
        if matches:
            return matches[0]
        matches = list(pane.query(ParamsTab))
        return matches[0] if matches else None

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
        if tab is not None and hasattr(tab, 'reset_editor'):
            tab.reset_editor()

    def action_clear_log(self) -> None:
        tab = self._active_tab()
        if tab is not None:
            tab.clear_log()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())
