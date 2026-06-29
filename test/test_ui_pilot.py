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

"""Headless UI tests: drive the textual app with Pilot against a FakeBridge (no rclpy)."""

import time
from concurrent.futures import Future

import pytest
import yaml
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from ros_tui.ros.events import ActionEvent, ActionEventKind
from ros_tui.ros.graph import GraphSnapshot, InterfaceEntry, NodeInfo
from ros_tui.ui.app import RosTuiApp
from ros_tui.ui.filterable_list import FilterableList
from ros_tui.ui.messages import NavigateToEntity
from ros_tui.ui.nodes_tab import _render_value
from textual.widgets import (
    Button,
    DataTable,
    Input,
    OptionList,
    RichLog,
    Static,
    TabbedContent,
    TextArea,
    Tree,
)

pytestmark = pytest.mark.ui

FIBONACCI_ENTRY = InterfaceEntry('/fibonacci', ('example_interfaces/action/Fibonacci',))
ADD_TWO_INTS_ENTRY = InterfaceEntry('/add_two_ints', ('example_interfaces/srv/AddTwoInts',))
CHATTER_ENTRY = InterfaceEntry('/chatter', ('std_msgs/msg/String',))
POSE_ENTRY = InterfaceEntry('/pose', ('geometry_msgs/msg/PoseStamped',))
TALKER_NODE = InterfaceEntry('/talker', ('/',))  # nodes store their namespace in types[0].

SNAPSHOT = GraphSnapshot(
    version=1,
    actions=(FIBONACCI_ENTRY,),
    services=(ADD_TWO_INTS_ENTRY, InterfaceEntry('/set_bool', ('std_srvs/srv/SetBool',))),
    topics=(CHATTER_ENTRY, POSE_ENTRY),
    nodes=(TALKER_NODE,),
)

# Canned introspection for /talker; entries match SNAPSHOT so jumps can highlight the target.
NODE_INFO = NodeInfo(
    node_name='/talker',
    publishers=(CHATTER_ENTRY,),
    subscribers=(POSE_ENTRY,),
    service_servers=(ADD_TWO_INTS_ENTRY,),
    service_clients=(),
    action_servers=(FIBONACCI_ENTRY,),
    action_clients=(),
)
NODE_PARAMS = [('use_sim_time', 'bool', False), ('rate', 'double', 10.0)]


def completed_future(result=None):
    future = Future()
    future.set_result(result)
    return future


class FakeBridge:
    def __init__(self, snapshot=SNAPSHOT):
        self.latest_graph = snapshot
        self.listener = None
        self.service_calls = []
        self.service_future = None
        self.sent_goals = []
        self.on_event = None
        self.cancelled = []
        self.published = []
        self.periodic_started = []
        self.periodic_stopped = []
        self.subscriptions = {}
        self.node_info_requests = []
        self.param_list_requests = []
        self.set_param_calls = []

    def set_graph_listener(self, listener):
        self.listener = listener

    def get_node_info(self, node_name, on_done):
        self.node_info_requests.append(node_name)
        on_done(NODE_INFO, None)

    def list_node_parameters(self, node_name, on_done):
        self.param_list_requests.append(node_name)
        on_done(list(NODE_PARAMS), None)

    def set_node_parameter(self, node_name, name, value_yaml, on_done):
        self.set_param_calls.append((node_name, name, value_yaml))
        on_done(None)

    def call_service(self, name, type_name, request, time_setters=()):
        self.service_calls.append((name, type_name, request))
        self.service_future = Future()
        return self.service_future

    def send_goal(self, name, type_name, goal, on_event, time_setters=()):
        self.sent_goals.append((name, type_name, goal))
        self.on_event = on_event

    def cancel_goal(self, name):
        self.cancelled.append(name)

    def publish_once(self, name, type_name, message, time_setters=()):
        self.published.append((name, type_name, message))
        return completed_future()

    def start_periodic_publish(self, name, type_name, message, rate_hz, time_setters=()):
        self.periodic_started.append((name, rate_hz))
        return completed_future()

    def stop_periodic_publish(self, name):
        self.periodic_stopped.append(name)
        return completed_future()

    def subscribe(self, name, type_name, buffer):
        self.subscriptions[name] = buffer
        return completed_future()

    def unsubscribe(self, name):
        self.subscriptions.pop(name, None)
        return completed_future()

    def shutdown(self):
        pass


async def wait_until(pilot, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await pilot.pause(0.05)
    return predicate()


async def click_button(pilot, selector):
    """Click and wait out the press animation — Buttons swallow clicks while '-active'."""
    await pilot.click(selector)
    await pilot.pause(0.25)


async def show_tab(pilot, tab_id):
    """Make a tab's pane active so it gets laid out; a hidden pane is sized 0×0,
    which silently drops RichLog writes. Tabs are switched via ctrl+t cycling, so
    set the active pane directly rather than pressing a numbered shortcut."""
    pilot.app.query_one(TabbedContent).active = tab_id
    await pilot.pause()


async def select_entry(pilot, tab, entry):
    tab.post_message(FilterableList.Selected(entry))
    # Wait for PrototypeReady to land (seed cached), not just for editor text: a late
    # prototype would overwrite any text the test loads into the editor afterwards.
    assert await wait_until(pilot, lambda: entry.name in tab._seed_cache), (
        f'prototype never loaded for {entry.name}'
    )


def log_text(tab):
    log = tab.query_one('#output-log', RichLog)
    return '\n'.join(strip.text for strip in log.lines)


def node_log_text(tab):
    log = tab.query_one('#node-param-log', RichLog)
    return '\n'.join(strip.text for strip in log.lines)


def node_status_text(tab):
    return static_text(tab.query_one('#node-param-status', Static))


def tree_leaf(tree, name_substr):
    """Return the first interface leaf whose label contains ``name_substr`` (or None)."""
    for branch in tree.root.children:
        for leaf in branch.children:
            if name_substr in str(leaf.label):
                return leaf
    return None


def tree_labels(tree):
    labels = []
    for branch in tree.root.children:
        labels.append(str(branch.label))
        labels.extend(str(leaf.label) for leaf in branch.children)
    return labels


async def select_node(pilot, app):
    """Activate the Nodes tab, select /talker, wait for its params + interfaces to load."""
    await show_tab(pilot, 'nodes')
    tab = app.query_one('#nodes-tab')
    tab.post_message(FilterableList.Selected(TALKER_NODE))
    table = tab.query_one('#node-params', DataTable)
    assert await wait_until(pilot, lambda: table.row_count == len(NODE_PARAMS))
    return tab


def static_text(widget):
    return str(widget.render())


def editor_error_text(tab):
    error_line = tab.query_one('#editor-error', Static)
    return static_text(error_line) if error_line.display else ''


async def test_tabs_show_entity_lists():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Every tab's list populates from the graph regardless of which pane is active.
        assert app.query_one('#actions-tab FilterableList OptionList', OptionList).option_count == 1
        assert app.query_one('#services-tab FilterableList OptionList', OptionList).option_count == 2
        assert app.query_one('#topics-tab FilterableList OptionList', OptionList).option_count == 2
        assert app.query_one('#nodes-tab FilterableList OptionList', OptionList).option_count == 1


async def test_filter_narrows_list():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')
        tab.query_one('#filter-input', Input).value = 'chat'
        option_list = tab.query_one('#entity-list', OptionList)
        assert await wait_until(pilot, lambda: option_list.option_count == 1)
        assert option_list.get_option_at_index(0).id == '/chatter'


async def test_filter_auto_highlights_first_match():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')
        option_list = tab.query_one('#entity-list', OptionList)
        # With no filter the full list still auto-highlights the first row.
        assert await wait_until(pilot, lambda: option_list.highlighted == 0)
        tab.query_one('#filter-input', Input).value = 'pose'
        assert await wait_until(
            pilot,
            lambda: option_list.option_count == 1 and option_list.highlighted == 0,
        )
        assert option_list.get_option_at_index(0).id == '/pose'


async def test_filter_arrows_move_highlight_while_input_focused():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        await pilot.press('ctrl+f')
        assert app.focused.id == 'filter-input'
        option_list = app.query_one('#topics-tab #entity-list', OptionList)
        assert await wait_until(pilot, lambda: option_list.option_count == 2)
        assert option_list.highlighted == 0
        await pilot.press('down')
        assert await wait_until(pilot, lambda: option_list.highlighted == 1)
        # Focus never leaves the filter input.
        assert app.focused.id == 'filter-input'
        await pilot.press('up')
        assert await wait_until(pilot, lambda: option_list.highlighted == 0)


async def test_filter_enter_selects_highlighted_match():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')
        await pilot.press('ctrl+f')
        tab.query_one('#filter-input', Input).value = 'pose'
        option_list = tab.query_one('#entity-list', OptionList)
        assert await wait_until(pilot, lambda: option_list.option_count == 1)
        await pilot.press('enter')
        assert await wait_until(
            pilot,
            lambda: tab.current_entry is not None and tab.current_entry.name == '/pose',
        )


async def test_selecting_topic_seeds_editor_with_defaults():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')
        await select_entry(pilot, tab, POSE_ENTRY)
        editor_text = tab.query_one('#editor', TextArea).text
        assert 'orientation:' in editor_text
        assert 'w: 1.0' in editor_text


async def test_invalid_yaml_blocks_call_with_inline_error():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'services')
        tab = app.query_one('#services-tab')
        await select_entry(pilot, tab, ADD_TWO_INTS_ENTRY)
        tab.query_one('#editor', TextArea).load_text('a: [unclosed')
        tab.primary_action()
        await pilot.pause()
        assert fake.service_calls == []
        assert 'YAML error' in editor_error_text(tab)
        # Field-level error: right structure, wrong value type.
        tab.query_one('#editor', TextArea).load_text('a: notanint\nb: 0')
        tab.primary_action()
        await pilot.pause()
        assert fake.service_calls == []
        assert editor_error_text(tab).startswith('a:')


async def test_call_sends_request_and_renders_response():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'services')
        tab = app.query_one('#services-tab')
        await select_entry(pilot, tab, ADD_TWO_INTS_ENTRY)
        tab.query_one('#editor', TextArea).load_text('a: 2\nb: 3')
        tab.primary_action()
        await pilot.pause()
        assert len(fake.service_calls) == 1
        _, _, request = fake.service_calls[0]
        assert request.a == 2 and request.b == 3
        assert tab.query_one('#call-button', Button).disabled
        fake.service_future.set_result(AddTwoInts.Response(sum=5))
        assert await wait_until(pilot, lambda: not tab.query_one('#call-button', Button).disabled)
        assert 'response in' in log_text(tab)
        assert 'sum: 5' in log_text(tab)


async def test_action_goal_feedback_result_render():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'actions')
        tab = app.query_one('#actions-tab')
        await select_entry(pilot, tab, FIBONACCI_ENTRY)
        tab.query_one('#editor', TextArea).load_text('order: 3')
        tab.primary_action()
        await pilot.pause()
        assert len(fake.sent_goals) == 1
        assert fake.sent_goals[0][2].order == 3
        assert tab.query_one('#send-button', Button).disabled
        assert not tab.query_one('#cancel-button', Button).disabled

        fake.on_event(ActionEvent('/fibonacci', ActionEventKind.ACCEPTED))
        status = tab.query_one('#goal-status', Static)
        assert await wait_until(pilot, lambda: 'EXECUTING' in static_text(status))
        fake.on_event(
            ActionEvent(
                '/fibonacci',
                ActionEventKind.FEEDBACK,
                payload=Fibonacci.Feedback(sequence=[0, 1, 1]),
            )
        )
        from action_msgs.msg import GoalStatus

        fake.on_event(
            ActionEvent(
                '/fibonacci',
                ActionEventKind.RESULT,
                payload=Fibonacci.Result(sequence=[0, 1, 1, 2]),
                status=GoalStatus.STATUS_SUCCEEDED,
            )
        )
        assert await wait_until(pilot, lambda: 'SUCCEEDED' in static_text(status))
        assert 'result: SUCCEEDED' in log_text(tab)
        assert not tab.query_one('#send-button', Button).disabled
        assert tab.query_one('#cancel-button', Button).disabled


async def test_rate_validation_and_start_stop():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')
        await select_entry(pilot, tab, CHATTER_ENTRY)
        tab.query_one('#rate-input', Input).value = '99999'
        await click_button(pilot, '#rate-button')
        assert fake.periodic_started == []
        assert 'rate must be within' in editor_error_text(tab)
        tab.query_one('#rate-input', Input).value = '10'
        await click_button(pilot, '#rate-button')
        assert fake.periodic_started == [('/chatter', 10.0)]
        assert str(tab.query_one('#rate-button', Button).label) == 'Stop rate'
        await click_button(pilot, '#rate-button')
        assert fake.periodic_stopped == ['/chatter']
        assert str(tab.query_one('#rate-button', Button).label) == 'Start rate'


async def test_echo_toggle_subscribes_and_unsubscribes():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')
        await select_entry(pilot, tab, CHATTER_ENTRY)
        await click_button(pilot, '#echo-button')
        assert '/chatter' in fake.subscriptions
        from std_msgs.msg import String

        fake.subscriptions['/chatter'].push(String(data='hello there'))
        assert await wait_until(pilot, lambda: 'hello there' in log_text(tab))
        await click_button(pilot, '#echo-button')
        assert '/chatter' not in fake.subscriptions


async def test_nodes_tab_present_and_labeled():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)):
        from ros_tui.ui.nodes_tab import NodesTab

        assert isinstance(app.query_one('#nodes-tab'), NodesTab)
        tab = app.query_one(TabbedContent).get_tab('nodes')
        assert 'Nodes' in str(tab.label)
        node_list = app.query_one('#nodes-tab FilterableList OptionList', OptionList)
        assert node_list.option_count == 1


async def test_selecting_node_shows_interfaces_and_params():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        assert fake.node_info_requests == ['/talker']
        assert fake.param_list_requests == ['/talker']
        labels = tree_labels(tab.query_one('#node-interfaces', Tree))
        assert any(label.startswith('Publishers (1)') for label in labels)
        assert any(label.startswith('Subscribers (1)') for label in labels)
        assert any(label.startswith('Service Servers (1)') for label in labels)
        assert any(label.startswith('Action Servers (1)') for label in labels)
        assert any(label.startswith('Service Clients (0)') for label in labels)
        assert any('/chatter' in label for label in labels)
        assert any('/fibonacci' in label for label in labels)
        # Parameter table populated from the bridge.
        rows = [tab.query_one('#node-params', DataTable).get_row_at(i)[0] for i in range(2)]
        assert rows == ['use_sim_time', 'rate']


async def _jump(pilot, app, leaf_substr):
    tab = await select_node(pilot, app)
    tree = tab.query_one('#node-interfaces', Tree)
    assert await wait_until(pilot, lambda: tree_leaf(tree, leaf_substr) is not None)
    leaf = tree_leaf(tree, leaf_substr)
    tab.on_tree_node_selected(Tree.NodeSelected(leaf))
    await pilot.pause()
    return leaf


async def test_publisher_leaf_jumps_to_topics_tab():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        leaf = await _jump(pilot, app, '/chatter')
        assert leaf.data[0] == 'topics'
        assert app.query_one(TabbedContent).active == 'topics'
        topics = app.query_one('#topics-tab')
        assert await wait_until(
            pilot,
            lambda: topics.current_entry is not None and topics.current_entry.name == '/chatter',
        )


async def test_service_leaf_jumps_to_services_tab():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        leaf = await _jump(pilot, app, '/add_two_ints')
        assert leaf.data[0] == 'services'
        assert app.query_one(TabbedContent).active == 'services'
        services = app.query_one('#services-tab')
        assert await wait_until(
            pilot,
            lambda: services.current_entry is not None
            and services.current_entry.name == '/add_two_ints',
        )


async def test_action_leaf_jumps_to_actions_tab():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        leaf = await _jump(pilot, app, '/fibonacci')
        assert leaf.data[0] == 'actions'
        assert app.query_one(TabbedContent).active == 'actions'
        actions = app.query_one('#actions-tab')
        assert await wait_until(
            pilot,
            lambda: actions.current_entry is not None
            and actions.current_entry.name == '/fibonacci',
        )


async def test_selecting_branch_does_not_navigate():
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        tree = tab.query_one('#node-interfaces', Tree)
        branch = tree.root.children[0]  # "Publishers (1)" — a category, data is None.
        assert branch.data is None
        tab.on_tree_node_selected(Tree.NodeSelected(branch))
        await pilot.pause()
        assert app.query_one(TabbedContent).active == 'nodes'  # No jump.


async def test_set_parameter_calls_bridge():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        table = tab.query_one('#node-params', DataTable)
        table.move_cursor(row=0)
        await pilot.pause()
        tab.query_one('#node-param-value', Input).value = 'true'
        tab.primary_action()
        await pilot.pause()
        assert fake.set_param_calls == [('/talker', 'use_sim_time', 'true')]
        assert await wait_until(pilot, lambda: 'set use_sim_time' in node_log_text(tab))


async def test_set_parameter_empty_value_shows_error():
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        tab.query_one('#node-params', DataTable).move_cursor(row=0)
        await pilot.pause()
        tab.query_one('#node-param-value', Input).value = '   '
        tab.primary_action()
        await pilot.pause()
        assert fake.set_param_calls == []
        assert 'enter a value to set' in node_status_text(tab)


async def test_node_tab_keybindings_dispatch_through_app():
    """The Nodes tab honours the app keybindings via the shared EntityTab verb contract.

    Unlike the other Nodes tests this drives the real ctrl+* bindings, so it guards the
    app._active_tab() resolution and the no-op verb hooks (e.g. ctrl+r has no editor here).
    """
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        assert app._active_tab() is tab  # active pane resolves to the NodesTab uniformly.

        # ctrl+s -> primary_action -> set the highlighted parameter.
        tab.query_one('#node-params', DataTable).move_cursor(row=0)
        await pilot.pause()
        tab.query_one('#node-param-value', Input).value = 'true'
        await pilot.press('ctrl+s')
        await pilot.pause()
        assert fake.set_param_calls == [('/talker', 'use_sim_time', 'true')]

        # ctrl+k -> secondary_action -> reload re-fetches both info and params.
        info_before, params_before = len(fake.node_info_requests), len(fake.param_list_requests)
        await pilot.press('ctrl+k')
        await pilot.pause()
        assert len(fake.node_info_requests) > info_before
        assert len(fake.param_list_requests) > params_before

        # ctrl+l -> clear_log -> clears the result log and the status line.
        tab._show_success('something')
        tab.query_one('#node-param-log', RichLog).write('a previous result')
        await pilot.pause()
        assert node_status_text(tab) != '' and node_log_text(tab) != ''
        await pilot.press('ctrl+l')
        await pilot.pause()
        assert node_status_text(tab) == '' and node_log_text(tab) == ''

        # ctrl+r -> reset_editor -> safe no-op on the Nodes tab (no editor to reset).
        await pilot.press('ctrl+r')
        await pilot.pause()
        assert node_status_text(tab) == ''  # unchanged, did not raise.

        # ctrl+f -> focus_filter -> focuses the node filter input.
        await pilot.press('ctrl+f')
        await pilot.pause()
        assert isinstance(app.focused, Input)
        assert app.focused.id == 'filter-input'


def test_render_value_blank_for_none():
    """A missing value renders blank (the input/table cell is simply empty)."""
    assert _render_value(None) == ''


@pytest.mark.parametrize(
    'value',
    [
        True, False, 0, 42, -7, 3.14, 1e-05, 1e20, -2.5e-10,
        'true', 'false', '42', '3.14', 'null', 'hello', 'with space', 'a: b', '',
        [1, 2, 3], [1.0, 2.0], ['x', 'y'], [True, False],
    ],
)
def test_render_value_round_trips(value):
    """What the Nodes tab shows must parse back (on Set) to the same value and type.

    Guards against re-typing string params like 'true'/'42' and exponential doubles
    like 1e-05 that a bare str() rendering would corrupt.
    """
    rendered = _render_value(value)
    assert '\n' not in rendered  # single-line; safe to seed a one-line Input / table cell.
    parsed = yaml.safe_load(rendered)
    assert parsed == value and type(parsed) is type(value)


async def test_entry_with_no_type_is_handled_gracefully():
    """An entry carrying no type must not crash navigation or filtering (guards types[0]).

    A Nodes-tab interface leaf can have an empty types tuple; jumping to it once raised
    IndexError on entry.types[0] in the destination tab and in the filter match.
    """
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'topics')
        tab = app.query_one('#topics-tab')
        typeless = InterfaceEntry('/mystery', ())

        # Navigation: selecting a typeless entry degrades to a message instead of crashing.
        tab.post_message(FilterableList.Selected(typeless))
        await pilot.pause()
        assert 'type' in static_text(tab.query_one('#detail-line', Static)).lower()

        # Filtering: a typeless entry in the list must not raise on the type-substring match.
        flist = tab.query_one(FilterableList)
        flist.set_entries((typeless, CHATTER_ENTRY))
        flist.query_one('#filter-input', Input).value = 'chat'
        flist._refresh_options()
        await pilot.pause()
        assert flist.border_subtitle.startswith('1/')  # /chatter matched; /mystery skipped.


async def test_param_value_box_follows_selection():
    """The value box always shows the highlighted row's value. Moving the cursor
    discards a value typed but not yet Set — favoured over a box that freezes on a
    stale value after a Set (every cursor move fires RowHighlighted).
    """
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        table = tab.query_one('#node-params', DataTable)
        input_box = tab.query_one('#node-param-value', Input)

        # The box seeds from the highlighted row (NODE_PARAMS: rate=10.0, use_sim_time=False).
        table.move_cursor(row=1)
        await pilot.pause()
        assert input_box.value == '10.0'
        table.move_cursor(row=0)
        await pilot.pause()
        assert input_box.value == 'false'

        # A value typed but not Set is replaced by the next selection's value.
        input_box.value = '999.0'
        table.move_cursor(row=1)
        await pilot.pause()
        assert input_box.value == '10.0'


class _FailingNodeBridge(FakeBridge):
    """A bridge whose node introspection and parameter list both fail."""

    def get_node_info(self, node_name, on_done):
        self.node_info_requests.append(node_name)
        on_done(None, 'node vanished')

    def list_node_parameters(self, node_name, on_done):
        self.param_list_requests.append(node_name)
        on_done(None, 'no parameter services')


async def test_node_load_failure_clears_loading_header():
    """When both info and params fail to load, the header must not stay on 'loading…'."""
    app = RosTuiApp(_FailingNodeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'nodes')
        tab = app.query_one('#nodes-tab')
        tab.post_message(FilterableList.Selected(TALKER_NODE))

        def header():
            return static_text(tab.query_one('#node-header', Static)).lower()

        assert await wait_until(pilot, lambda: 'failed' in header())
        assert 'loading' not in header()


class _NoParamsBridge(FakeBridge):
    """A bridge whose nodes expose no parameters."""

    def list_node_parameters(self, node_name, on_done):
        self.param_list_requests.append(node_name)
        on_done([], None)


async def test_set_with_no_parameter_selected_reports_error():
    """Set with nothing selectable must report an error, not silently no-op."""
    fake = _NoParamsBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'nodes')
        tab = app.query_one('#nodes-tab')
        tab.post_message(FilterableList.Selected(TALKER_NODE))
        assert await wait_until(pilot, lambda: tab._params == [])

        tab.primary_action()  # ctrl+s with no selectable parameter row
        await pilot.pause()
        assert fake.set_param_calls == []
        assert 'select a parameter' in node_status_text(tab).lower()


async def test_set_results_accumulate_in_log():
    """Each Set result stays visible in the scrollable log, not overwritten (history)."""
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        table = tab.query_one('#node-params', DataTable)
        input_box = tab.query_one('#node-param-value', Input)

        table.move_cursor(row=0)  # use_sim_time
        await pilot.pause()
        input_box.value = 'true'
        tab.primary_action()
        await pilot.pause()

        table.move_cursor(row=1)  # rate
        await pilot.pause()
        input_box.value = '5.0'
        tab.primary_action()
        await pilot.pause()

        assert await wait_until(
            pilot,
            lambda: 'set use_sim_time' in node_log_text(tab) and 'set rate' in node_log_text(tab),
        ), f'both set results should remain in the log: {node_log_text(tab)!r}'
        assert fake.set_param_calls == [
            ('/talker', 'use_sim_time', 'true'),
            ('/talker', 'rate', '5.0'),
        ]


async def test_navigate_to_non_interface_tab_is_noop():
    """A NavigateToEntity at a non-InterfaceTab pane switches tabs without crashing.

    The Nodes tab is an EntityTab but not an InterfaceTab; resolving the destination
    through the EntityTab contract makes select_entity an inherited no-op there.
    """
    app = RosTuiApp(FakeBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(NavigateToEntity('nodes', CHATTER_ENTRY))
        await pilot.pause()
        assert app.query_one(TabbedContent).active == 'nodes'


async def test_reselecting_current_node_skips_reintrospection():
    """Re-selecting the displayed node reuses cached info/params; Refresh still re-fetches."""
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        info_before = len(fake.node_info_requests)
        params_before = len(fake.param_list_requests)

        tab.post_message(FilterableList.Selected(TALKER_NODE))  # same node again
        await pilot.pause()
        assert len(fake.node_info_requests) == info_before
        assert len(fake.param_list_requests) == params_before

        await pilot.press('ctrl+k')  # explicit Refresh
        await pilot.pause()
        assert len(fake.node_info_requests) > info_before
        assert len(fake.param_list_requests) > params_before


async def test_set_targets_the_highlighted_row():
    """Set sends the highlighted parameter, even after moving off row 0 (single source)."""
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        tab.query_one('#node-params', DataTable).move_cursor(row=1)  # 'rate', not 'use_sim_time'
        await pilot.pause()
        tab.query_one('#node-param-value', Input).value = '7.5'
        tab.primary_action()
        await pilot.pause()
        assert fake.set_param_calls == [('/talker', 'rate', '7.5')]


async def test_set_then_select_another_parameter():
    """After a successful Set, the value box must follow a new selection instead of
    staying frozen on the just-submitted value (regression: the edit-preservation
    guard left the box permanently 'dirty' once a value had been set)."""
    fake = FakeBridge()
    app = RosTuiApp(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        tab = await select_node(pilot, app)
        table = tab.query_one('#node-params', DataTable)
        input_box = tab.query_one('#node-param-value', Input)

        table.move_cursor(row=0)  # use_sim_time
        await pilot.pause()
        input_box.value = 'true'
        tab.primary_action()
        await pilot.pause()
        assert await wait_until(pilot, lambda: 'set use_sim_time' in node_log_text(tab))

        # Selecting a different parameter must refresh the value box to that row's value.
        table.move_cursor(row=1)  # rate = 10.0
        await pilot.pause()
        assert input_box.value == '10.0', f'value box frozen at {input_box.value!r} after Set'

        # ...and Set must now target that newly selected parameter.
        input_box.value = '5.0'
        tab.primary_action()
        await pilot.pause()
        assert fake.set_param_calls[-1] == ('/talker', 'rate', '5.0')


_MANY_PARAMS = [(f'param_{i:02d}', 'int', i) for i in range(12)]


class _ManyParamsBridge(FakeBridge):
    """A node with few interfaces but many parameters — the parameter table, not the
    interfaces tree, should get the vertical space."""

    def get_node_info(self, node_name, on_done):
        self.node_info_requests.append(node_name)
        on_done(NodeInfo('/talker', (CHATTER_ENTRY,), (), (), (), (), ()), None)

    def list_node_parameters(self, node_name, on_done):
        self.param_list_requests.append(node_name)
        on_done(list(_MANY_PARAMS), None)


async def test_parameter_block_is_40_percent_and_scrolls():
    """The interfaces tree and parameters block split the available height ~60/40, each
    filling its share and scrolling when its content overflows. Regression for the tree
    ballooning past its content while the parameter table was choked (and an empty result
    log eating the bottom)."""
    app = RosTuiApp(_ManyParamsBridge())
    async with app.run_test(size=(120, 40)) as pilot:
        await show_tab(pilot, 'nodes')
        tab = app.query_one('#nodes-tab')
        tab.post_message(FilterableList.Selected(TALKER_NODE))
        table = tab.query_one('#node-params', DataTable)
        assert await wait_until(pilot, lambda: table.row_count == len(_MANY_PARAMS))
        await pilot.pause()

        tree = tab.query_one('#node-interfaces')
        group = tab.query_one('#node-params-group')
        log = tab.query_one('#node-param-log', RichLog)
        # Parameters block is ~40% of the two-block height; the tree takes the rest.
        ratio = group.region.height / (tree.region.height + group.region.height)
        assert 0.37 <= ratio <= 0.43, f'parameters block should be ~40%, was {ratio:.0%}'
        # More params than fit must scroll inside the table, not resize the block.
        assert table.virtual_size.height > table.region.height, (
            'table should scroll when params overflow its share'
        )
        # The empty result log takes no space at all until a Set writes to it.
        assert log.region.height == 0, f'empty log should take no space, was {log.region.height}'
