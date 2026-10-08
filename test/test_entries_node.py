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

"""The node entry (ros_tui/ui/entries/node.py), without textual.

The nav model runs over the demo world with a canned FakeBridge (it answers at once), except in
the loading test, which uses the live one and its clock.
"""

import pytest
from harness.fake_bridge import DEMO_PARAMS, SERVICE_DELAY_S, FakeBridge
from harness.live_world import live_nav, press
from ros_tui.ui.entries.base import Entry
from ros_tui.ui.entries.action import ActionEntry
from ros_tui.ui.entries.node import NodeEntry, Param, parse_value, render_value
from ros_tui.ui.nav import AREA, EDIT, IN, Tab

NODE = '/ros_tui_demo_servers'
NODE_TAB = Tab('nodes', NODE)
OPEN_NODE = ['G', 'k', 'enter']  # The last two rows of the ☰ list are /ros_tui_demo_servers and /talker.
TO_RATE = ['l', 'enter', 'j']  # PARAMETERS, inside, the publish_rate row.


def node_nav(*keys, bridge=None):
    """Over the canned FakeBridge (it answers at once) unless given the live one."""
    return live_nav(*keys, bridge=bridge or FakeBridge())


def node_data(nav):
    return nav.entry(NODE_TAB)


@pytest.mark.parametrize('kind, text, value', [
    ('bool', 'true', True), ('bool', 'FALSE', False), ('bool', ' True ', True),
    ('int', '5', 5), ('int', '-3', -3),
    ('double', '5', 5.0), ('double', '1e-3', 0.001), ('double', '-2.5', -2.5),
    ('string', 'odom', 'odom'), ('string', '42', '42'),
    ('int[]', '[1, 2]', [1, 2]),
])
def test_parse_value(kind, text, value):
    parsed = parse_value(Param('p', kind, None), text)
    assert parsed == value and type(parsed) is type(value)


@pytest.mark.parametrize('param, text, message', [
    (Param('use_sim_time', 'bool', False), 'x', 'use_sim_time needs true or false, got "x"'),
    (Param('use_sim_time', 'bool', False), '1', 'use_sim_time needs true or false, got "1"'),
    (Param('publish_rate', 'double', 10.0), '5x', 'publish_rate needs a number, got "5x"'),
    (Param('publish_rate', 'double', 10.0), '', 'publish_rate needs a number, got ""'),
    (Param('count', 'int', 3), '2.5', 'count needs a whole number, got "2.5"'),
    (Param('ids', 'int[]', [1]), '7', 'ids needs a list like [1, 2], got "7"'),
])
def test_parse_value_errors_name_the_parameter(param, text, message):
    with pytest.raises(ValueError) as error:
        parse_value(param, text)
    assert str(error.value) == message


@pytest.mark.parametrize('value, text', [
    (False, 'false'), (10.0, '10.0'), (5, '5'), ('map', 'map'), ('true', "'true'"), ('10', "'10'"),
    (1e-05, '1.0e-05'), ([1, 2], '[1, 2]'), (None, ''),
])
def test_render_value_round_trips(value, text):
    assert render_value(value) == text


def test_open_loads_interfaces_and_parameters():
    nav, bridge = node_nav(*OPEN_NODE)
    data = node_data(nav)
    assert bridge.node_info_requests == [NODE] and bridge.param_list_requests == [NODE]
    assert [(title, [i.name for i in rows]) for title, rows in data.groups] == [
        ('Publishes', ['/chatter', '/counter', '/diagnostic_status', '/localisation_pose']),
        ('Subscribes', ['/inbox', '/goal_pose']),
        ('Serves', ['/add_two_ints', '/set_pose']),
        ('Action server', ['/fibonacci']),
    ]
    assert [p.name for p in data.params] == ['use_sim_time', 'publish_rate', 'frame_id']
    assert nav.summary()['area'] == 'ifs' and nav.row_count() == 9
    assert nav.footer()[1:4] == (('tabs', NODE), 'tab row', 'into interfaces')


def test_loading_until_the_bridge_answers():
    bridge = FakeBridge.demo()
    nav, _ = node_nav(*OPEN_NODE, bridge=bridge)
    data = node_data(nav)
    assert data.groups is None and data.params is None and nav.row_count() == 0
    bridge.clock.advance(SERVICE_DELAY_S)
    assert data.groups and data.params


class UnreachableNode(FakeBridge):
    """A node that is gone: its interfaces and parameters both fail to load."""

    def get_node_info(self, node_name, on_done):
        on_done(None, 'node vanished')

    def list_node_parameters(self, node_name, on_done):
        on_done(None, 'no parameter services')


def test_a_node_that_does_not_answer_says_why():
    nav, _ = node_nav(*OPEN_NODE, bridge=UnreachableNode())
    data = node_data(nav)
    assert (data.info_error, data.params_error) == ('node vanished', 'no parameter services')
    assert data.groups is None and data.params is None and nav.row_count() == 0


def test_space_with_nothing_changed_sets_nothing():
    nav, bridge = node_nav(*OPEN_NODE, 'space')
    assert bridge.set_param_calls == []
    assert nav.feedback.toast.text == 'change a value first (enter edits it)'


def test_a_reload_keeps_the_cursor_and_the_edit_on_their_parameter():
    nav, bridge = node_nav(*OPEN_NODE, 'l', 'enter', 'G')  # frame_id, row 2.
    bridge.params = DEMO_PARAMS[1:]
    nav.entry(NODE_TAB).on_open(nav)  # The list shrinks: the cursor stays within it.
    assert nav.row_index() == 1
    press(nav, 'c', *'odom')
    bridge.params = DEMO_PARAMS
    nav.entry(NODE_TAB).on_open(nav)  # It grows back while frame_id is typed (now row 2 again).
    press(nav, 'enter')
    assert node_data(nav).changes == {'frame_id': 'odom'}


def test_enter_on_an_interface_opens_it_in_a_tab():
    nav, _ = node_nav(*OPEN_NODE, 'enter', *['j'] * 6, 'enter')
    assert nav.tab == Tab('services', '/add_two_ints') and nav.layer == IN
    assert nav.feedback.log[0] == ('enter', 'opened /add_two_ints (tab 2)')


def test_edit_a_parameter_with_a_bad_value_then_keep_it():
    nav, bridge = node_nav(*OPEN_NODE, *TO_RATE, 'enter')
    assert nav.layer == EDIT and nav.editing.value == '10.0' and not nav.editing.fresh
    assert nav.footer().mode == 'insert' and nav.footer().path == ('tabs', NODE, 'parameters', 'editing')
    press(nav, *['backspace'] * 4, '5', 'x', 'enter')
    assert nav.layer == EDIT and nav.feedback.errline(NODE_TAB) == 'publish_rate needs a number, got "5x"'
    press(nav, 'backspace', 'enter')
    assert nav.layer == AREA and nav.feedback.errline(NODE_TAB) == ''
    assert node_data(nav).changes == {'publish_rate': 5.0}
    assert nav.feedback.log[0] == ('enter', 'publish_rate = 5.0 (not set yet: space sets it, u undoes)')
    assert bridge.set_param_calls == []  # Nothing is sent before space.


def test_esc_on_a_bad_value_keeps_the_old_one():
    nav, _ = node_nav(*OPEN_NODE, 'l', 'enter', 'enter', 'x', 'escape')
    assert nav.layer == AREA and node_data(nav).changes == {}
    assert nav.summary()['toast'] == ['use_sim_time needs true or false, got "x" — kept the old value', 'bad']


def test_a_bool_starts_fresh_and_c_clears():
    nav, _ = node_nav(*OPEN_NODE, 'l', 'enter', 'enter')
    assert nav.editing.fresh and nav.editing.value == 'false'
    press(nav, *'true', 'enter')
    assert node_data(nav).changes == {'use_sim_time': True}
    press(nav, 'j', 'j', 'c')
    assert nav.layer == EDIT and nav.editing.value == '' and nav.editing.field == 'frame_id'
    press(nav, *'odom', 'escape')
    assert node_data(nav).changes == {'use_sim_time': True, 'frame_id': 'odom'}


def test_typing_the_old_value_back_is_no_change():
    nav, _ = node_nav(*OPEN_NODE, *TO_RATE, 'c', '7', 'enter')
    assert node_data(nav).changes == {'publish_rate': 7.0}
    press(nav, 'c', *'10', 'enter')
    assert node_data(nav).changes == {} and nav.feedback.log[0] == ('enter', 'publish_rate unchanged')
    press(nav, 'enter', 'enter')  # Unchanged again: no new undo step.
    assert len(nav.undo_stack) == 2


def test_space_sets_the_changed_parameters():
    nav, bridge = node_nav(*OPEN_NODE, 'space')
    assert nav.summary()['toast'] == ['change a value first (enter edits it)', 'bad']
    assert bridge.set_param_calls == []
    press(nav, 'l', 'enter', 'enter', *'true', 'enter', 'j', 'c', '5', 'enter', 'space')
    assert bridge.set_param_calls == [(NODE, 'use_sim_time', 'true'), (NODE, 'publish_rate', '5.0')]
    assert [line.text for line in nav.feedback.activity] == ['✓ set publish_rate = 5.0', '✓ set use_sim_time = true']
    data = node_data(nav)
    assert data.changes == {} and [p.value for p in data.params] == [True, 5.0, 'map']
    assert nav.feedback.log[0] == ('space', f'set 2 parameters on {NODE}')


def test_ctrl_s_in_insert_keeps_and_sets():
    nav, bridge = node_nav(*OPEN_NODE, *TO_RATE, 'c', '2', 'ctrl+s')
    assert nav.layer == AREA and bridge.set_param_calls == [(NODE, 'publish_rate', '2.0')]


def test_a_failed_set_keeps_the_change():
    nav, bridge = node_nav(*OPEN_NODE)
    bridge.rejected_params['frame_id'] = 'frame_id is read-only'
    press(nav, 'l', 'enter', 'G', 'c', *'odom', 'enter', 'space')
    assert nav.feedback.activity[0].text == '✗ set frame_id: frame_id is read-only' and nav.feedback.activity[0].cls == 'r'
    assert node_data(nav).changes == {'frame_id': 'odom'}


def test_undo_only_in_this_tab():
    nav, _ = node_nav(*OPEN_NODE, *TO_RATE, 'c', '5', 'enter', '0', 'g', 'g', 'enter')  # Change it, open /chatter.
    assert nav.tab == Tab('topics', '/chatter')
    press(nav, 'u')
    assert nav.feedback.log[0] == ('u', 'nothing to undo here')
    assert node_data(nav).changes == {'publish_rate': 5.0}
    press(nav, '1', 'u')
    assert node_data(nav).changes == {} and nav.feedback.log[0] == ('u', f'undid the change to publish_rate on {NODE}')


def test_undo_steps_back_through_changes():
    nav, _ = node_nav(*OPEN_NODE, *TO_RATE, 'c', '5', 'enter', 'c', '6', 'enter', 'u')
    assert node_data(nav).changes == {'publish_rate': 5.0}
    press(nav, 'u')
    assert node_data(nav).changes == {}


def test_reopening_keeps_changes_that_are_not_set():
    nav, bridge = node_nav(*OPEN_NODE, *TO_RATE, 'c', '5', 'enter', '0', 'G', 'k', 'enter')
    assert bridge.param_list_requests == [NODE, NODE]
    assert node_data(nav).changes == {'publish_rate': 5.0}


def test_each_tab_gets_an_entry_of_its_kind():
    nav, _ = node_nav('/', *'fib', 'enter')
    assert nav.tab.kind == 'actions' and isinstance(nav.entry(nav.tab), ActionEntry)
    assert isinstance(nav.entry(NODE_TAB), NodeEntry) and nav.entry(NODE_TAB) is nav.entry(NODE_TAB)
    assert type(nav.entry(Tab('things', '/x'))) is Entry  # A kind without a class of its own gets the base.


def test_a_set_change_leaves_nothing_to_undo():
    """Once the node has the value, u has nothing left to undo there (it would only log a no-op)."""
    nav, _ = node_nav(*OPEN_NODE, *TO_RATE, 'c', '5', 'enter', 'c', '6', 'enter', 'space')
    assert node_data(nav).changes == {} and nav.undo_stack == []
    press(nav, 'u')
    assert nav.feedback.log[0] == ('u', 'nothing to undo here')
