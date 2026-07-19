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

"""The textual application: four tabs over one shared RosBridge."""

from textual.app import App
from textual.binding import Binding
from textual.containers import Center, Middle
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from ros_tui.ui.actions_tab import ActionsTab
from ros_tui.ui.entity_tab import EntityTab
from ros_tui.ui.messages import GraphUpdated, NavigateToEntity
from ros_tui.ui.nodes_tab import NodesTab
from ros_tui.ui.services_tab import ServicesTab
from ros_tui.ui.topics_tab import TopicsTab

HELP_TEXT = """\
ros_tui — ROS 2 interface workbench

  ctrl+t                     cycle tabs: Topics → Services → Actions → Nodes
  ctrl+f                     back to the list (filter box focused) from the detail view
                             (↑/↓ move through matches, enter selects the highlighted one)
  ctrl+s                     primary action: Send goal / Call / Publish once / Set param
  ctrl+k                     Cancel goal / Stop periodic publish / Refresh node
  ctrl+r                     reset the editor to the message defaults
  ctrl+l                     clear the output log of the current tab
  f2                         this help · esc closes it
  ctrl+q                     quit

On the Nodes tab, select an interface in the tree to jump to its
Topics / Services / Actions tab with that entity pre-selected.

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
        Binding('f2', 'dismiss_help', 'Close', show=False, priority=True),
    ]

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen Static { width: 100; max-width: 95%; border: round $primary; padding: 1 2; }
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
    .entity-list { width: 1fr; min-width: 28; border: round $primary; }
    .entity-list #filter-input { border: none; height: 1; padding: 0 1; }
    .entity-list #entity-list { height: 1fr; border: none; }
    /* Keep the highlighted row a dark gray in both focus states. Textual otherwise
       paints the focused option with the cyan block cursor, which collides with the
       cyan message-type text and makes it unreadable. */
    .entity-list #entity-list > .option-list--option-highlighted,
    .entity-list #entity-list:focus > .option-list--option-highlighted {
        background: $surface-lighten-2;
        color: $text;
    }
    /* Tabs start maximized (list only); selecting an entry reveals the right pane. */
    .right-pane { width: 1fr; padding: 0 1; display: none; }
    #detail-title, #node-title { height: 1; color: $primary; text-style: bold; }
    #detail-line, #node-header { height: 1; color: $text-muted; }
    #editor { height: 3fr; min-height: 5; border: round $surface-lighten-2; }
    #editor-error { display: none; height: auto; max-height: 3; }
    .controls { height: 3; }
    .controls Button { margin-right: 1; min-width: 8; }
    #rate-input { width: 9; }
    #goal-status, #topics-status { height: 1; }
    #output-log { height: 2fr; min-height: 5; border: round $surface-lighten-2; }
    /* Split the available height ~60/40 between the interfaces tree and the
       parameters block. Each fills its share and scrolls when its content
       overflows (3fr:2fr -> parameters get 40% of the space below the header). */
    #node-interfaces { height: 3fr; min-height: 6; border: round $surface-lighten-2; }
    #node-params-group { height: 2fr; min-height: 10; border: round $surface-lighten-2; }
    #node-params { height: 1fr; min-height: 5; border: none; }
    #node-param-value { width: 1fr; }
    #node-param-status { height: 1; }
    /* The result log takes no space until a Set writes to it, then grows (capped)
       to show the ✓/✗ history; the parameter table absorbs the room until then. */
    #node-param-log { height: auto; max-height: 6; }
    """

    BINDINGS = [
        Binding('ctrl+t', 'cycle_tab', 'Next tab', priority=True),
        Binding('ctrl+f', 'focus_filter', 'Back to list', priority=True),
        Binding('ctrl+s', 'primary_action', 'Send/Call/Pub', priority=True),
        Binding('ctrl+k', 'secondary_action', 'Cancel/Stop', priority=True),
        Binding('ctrl+r', 'reset_editor', 'Reset msg', priority=True),
        Binding('ctrl+l', 'clear_log', 'Clear log', priority=True),
        Binding('f2', 'help', 'Help'),
    ]

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge
        self._jumping = False  # True while a cross-tab jump owns the next tab switch.
        self._activated_once = False  # Guards the mount-time TabActivated (see handler).

    def compose(self):
        yield Header()
        with TabbedContent(initial='topics'):
            with TabPane('Topics', id='topics'):
                yield TopicsTab(self._bridge, id='topics-tab')
            with TabPane('Services', id='services'):
                yield ServicesTab(self._bridge, id='services-tab')
            with TabPane('Actions', id='actions'):
                yield ActionsTab(self._bridge, id='actions-tab')
            with TabPane('Nodes', id='nodes'):
                yield NodesTab(self._bridge, id='nodes-tab')
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
        self.query_one('#topics-tab', TopicsTab).set_entries(snapshot.topics)
        self.query_one('#services-tab', ServicesTab).set_entries(snapshot.services)
        self.query_one('#actions-tab', ActionsTab).set_entries(snapshot.actions)
        self.query_one('#nodes-tab', NodesTab).set_entries(snapshot.nodes)

    def on_navigate_to_entity(self, message: NavigateToEntity) -> None:
        message.stop()
        tabbed = self.query_one(TabbedContent)
        # Drop focus first, same as action_cycle_tab: TabbedContent silently reverts an
        # `active` change while a descendant widget holds focus.
        self.set_focus(None)
        # Suppress the activation-driven maximize: a jump opens the destination minimized,
        # showing the jumped-to entity. The flag is consumed by the TabActivated handler
        # below, whichever order it and the Selected (minimize) end up running in.
        self._jumping = True
        tabbed.active = message.tab_id
        # Resolve the destination through the shared EntityTab contract; a tab_id that does
        # not map to an EntityTab (a typo, or a non-jumpable tab) is a no-op, not a crash.
        destinations = list(self.query(f'#{message.tab_id}-tab'))
        tab = destinations[0] if destinations else None
        if isinstance(tab, EntityTab):
            tab.select_entity(message.entry)

    def on_tabbed_content_tab_activated(self, message: TabbedContent.TabActivated) -> None:
        # Every way of switching tabs (click, ctrl+t, programmatic) lands here. A tab with
        # no selection opens maximized with the filter box focused, ready to type; a tab
        # that already has a selected item restores that item's detail view instead (an
        # extra ctrl+f returns to the list). A cross-tab jump is handled separately below.
        if self._jumping:
            self._jumping = False
            return
        tab = self._active_tab()
        if tab is None:
            return
        # The first activation is the mount-time one for the initial tab; just maximize it.
        # Focusing the filter here would schedule a deferred focus that a very fast first
        # ctrl+t could race (landing focus in the old pane, reverting the switch), and the
        # user did not switch to this tab — it is simply the startup tab.
        if not self._activated_once:
            self._activated_once = True
            tab.maximize_list()
        elif tab.has_selection():
            tab.minimize_list()
        else:
            tab.focus_filter()

    def _active_tab(self) -> EntityTab | None:
        tabbed = self.query_one(TabbedContent)
        if not tabbed.active:
            return None
        matches = list(tabbed.get_pane(tabbed.active).query(EntityTab))
        return matches[0] if matches else None

    def action_cycle_tab(self) -> None:
        tabbed = self.query_one(TabbedContent)
        pane_ids = [pane.id for pane in tabbed.query(TabPane)]
        if not pane_ids:
            return
        try:
            index = pane_ids.index(tabbed.active)
        except ValueError:
            index = -1
        # Drop focus first: while a widget inside the active pane holds focus,
        # TabbedContent silently reverts an `active` change, so the switch only
        # worked when the tab bar itself was focused (e.g. just after clicking).
        self.set_focus(None)
        tabbed.active = pane_ids[(index + 1) % len(pane_ids)]

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
