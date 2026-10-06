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

"""The field helpers (ros_tui/ui/helpers/) on their own, then in the message editors without textual.

The popup model over real message structures: which rows get which helper, the Quaternion modes
(yaw 90 is {x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}), the Header and Time modes and the values
they write, an enum's options, and typing an enum's name or prefix in insert. Then f / enter / esc /
u through NavState in a topic's message, a service's request and an action's goal. The pure maths
(quaternions, stamps, reading a header back) comes first.
"""

import math
from dataclasses import replace

import pytest
from harness.fake_bridge import CAMERA_INFO_SERVICE, DEMO_GRAPH, FakeBridge, camera_demo
from ros_tui.ros.graph import InterfaceEntry
from ros_tui.ros.message_yaml import message_structure
from ros_tui.ui.entries import entry_router
from ros_tui.ui.fields import FieldRows, enum_matches, enum_value
from ros_tui.ui.helpers import ENUM, HEADER, QUAT, TIME, Helper, helper_kind, helper_name
from ros_tui.ui.helpers.header import parse_header
from ros_tui.ui.helpers.quaternion import clean_quat, normalize_quat, quat_about_axis, quat_from_euler
from ros_tui.ui.helpers.time import parse_time, seconds_str_to_stamp, stamp_to_seconds_str
from ros_tui.ui.keymap import KeyRow, key_char, keys_now
from ros_tui.ui.nav import AREA, EDIT, NavState, Tab
from ros_tui.ui.widgets.entry_body import row_line

YAW_90 = {'x': 0.0, 'y': 0.0, 'z': 0.707107, 'w': 0.707107}
IDENTITY = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0}
LEVELS = (('OK', 0), ('WARN', 1), ('ERROR', 2), ('STALE', 3))
LOOKUP = InterfaceEntry('/lookup_transform', ('tf2_msgs/action/LookupTransform',))


def rows(type_name: str, values: dict | None = None, kind: str = 'msg') -> dict:
    """Every row of `type_name`, nested messages unfolded, by field."""
    form = FieldRows(message_structure(kind, type_name), values)
    for _ in range(4):
        for row in form.rows():
            if row.folds and not row.open and row.shape == 'message':
                form.toggle(form.index_of(row.path))
    return {row.field: row for row in form.rows()}


def pose(orientation=None, header='auto') -> dict:
    return {'header': header, 'pose': {'position': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                                       'orientation': orientation or dict(IDENTITY)}}


def press(helper: Helper, *keys: str) -> Helper:
    for key in keys:
        helper.press(key, key_char(key))
    return helper


def quat_helper(orientation=None) -> Helper:
    return Helper.open(rows('geometry_msgs/msg/PoseStamped', pose(orientation))['pose.orientation'])


def header_helper(header) -> Helper:
    return Helper.open(rows('geometry_msgs/msg/PoseStamped', pose(header=header))['header'])


# ---------- the pure maths ----------
def test_quaternion_maths():
    assert normalize_quat(1.0, 1.0, 1.0, 1.0) == (0.5, 0.5, 0.5, 0.5)
    assert normalize_quat(0.0, 0.0, 0.0, 0.0) == (0.0, 0.0, 0.0, 1.0)
    cleaned = clean_quat(1e-9, -0.0, 0.50000049, 0.99999999)
    assert cleaned == {'x': 0.0, 'y': 0.0, 'z': 0.5, 'w': 1.0}
    assert math.copysign(1.0, cleaned['y']) == 1.0  # -0.0 became +0.0.
    assert quat_about_axis(0.0, 0.0, 0.0, 1.5) == (0.0, 0.0, 0.0, 1.0)
    assert quat_about_axis(0.0, 0.0, 1.0, math.pi / 2) == pytest.approx(quat_from_euler(0.0, 0.0, math.pi / 2))
    # Reference values from transforms3d (what tf_transformations wraps), sxyz order, xyzw out.
    assert quat_from_euler(0.5, 0.2, -0.3) == pytest.approx((0.25786, 0.05886, -0.16849, 0.94956), abs=1e-5)


@pytest.mark.parametrize('text, stamp', [
    ('2.5', {'sec': 2, 'nanosec': 500000000}), ('7', {'sec': 7, 'nanosec': 0}),
    ('.25', {'sec': 0, 'nanosec': 250000000}),
    ('1.0000000009', {'sec': 1, 'nanosec': 0}),  # Past nanoseconds is cut, not rounded.
])
def test_seconds_to_a_stamp(text, stamp):
    assert seconds_str_to_stamp(text) == stamp


@pytest.mark.parametrize('text', ['-1', 'abc'])
def test_seconds_to_a_stamp_rejects(text):
    with pytest.raises(ValueError):
        seconds_str_to_stamp(text)


def test_a_stamp_reads_back():
    assert stamp_to_seconds_str({'sec': 2, 'nanosec': 500000000}) == '2.5'
    assert stamp_to_seconds_str({'sec': 7, 'nanosec': 0}) == '7'
    assert stamp_to_seconds_str({'sec': 2, 'nanosec': 7}) == '2.000000007'
    assert parse_time({'sec': 2, 'nanosec': 500000000}) == ('seconds', '2.5')
    assert parse_time('now') == parse_time(None) == ('now', '0.0')
    assert parse_header({'stamp': {'sec': 5, 'nanosec': 7}, 'frame_id': 'map'}) == (
        'manual', 'map', {'sec': 5, 'nanosec': 7})
    assert parse_header({'stamp': 'now', 'frame_id': 'odom'}) == ('now', 'odom', None)
    assert parse_header('auto') == ('auto', '', None)


# ---------- which rows have a helper ----------
def test_rows_with_a_helper():
    pose_rows = rows('geometry_msgs/msg/PoseStamped', pose())
    assert {field: helper_kind(row) for field, row in pose_rows.items()} == {
        'header': HEADER, 'pose': None, 'pose.position': None, 'pose.orientation': QUAT}
    assert helper_name(pose_rows['pose.orientation']) == 'Quaternion' and helper_name(pose_rows['header']) == 'Header'
    status = rows('diagnostic_msgs/msg/DiagnosticStatus')
    assert helper_kind(status['level']) == ENUM and helper_name(status['level']) == 'Enum'
    assert helper_kind(status['name']) is None and helper_name(None) is None
    goal = rows('tf2_msgs/action/LookupTransform', kind='action')
    assert helper_kind(goal['source_time']) == TIME and helper_kind(goal['timeout']) is None  # Duration: none.
    assert Helper.open(status['name']) is None


# ---------- quaternion ----------
def test_quaternion_opens_on_the_raw_values():
    helper = quat_helper()
    assert (helper.field, helper.type, helper.name, helper.mode) == ('pose.orientation', 'Quaternion', 'Quaternion', 0)
    assert [mode.name for mode in helper.modes()] == ['x y z w', 'roll pitch yaw (°)', 'yaw only (°)',
                                                      'axis + angle (°)']
    assert helper.fields() == ('x', 'y', 'z', 'w') and [helper.values[f] for f in 'xyzw'] == ['0.0', '0.0', '0.0', '1.0']
    assert helper.result() == (IDENTITY, '{x: 0.0, y: 0.0, z: 0.0, w: 1.0}')


def test_yaw_only_90():
    helper = press(quat_helper(), 'tab', 'tab', '9', '0')
    assert helper.modes()[helper.mode].name == 'yaw only (°)' and helper.values['yaw'] == '90'
    assert helper.result() == (YAW_90, '{x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}')


def test_roll_pitch_yaw():
    helper = press(quat_helper(), 'tab', 'right', 'right', '9', '0')
    assert helper.fields() == ('roll', 'pitch', 'yaw') and helper.cur == 2
    assert helper.result().value == YAW_90
    press(helper, 'left', 'left', '1', '8', '0', 'down', 'down', 'backspace', 'backspace', '0')
    assert helper.result().value == {'x': 1.0, 'y': 0.0, 'z': 0.0, 'w': 0.0}  # roll 180, yaw 0.


def test_axis_and_angle():
    helper = press(quat_helper(), 'shift+tab', 'down', 'down', 'down', '9', '0')
    assert helper.fields() == ('ax', 'ay', 'az', 'angle') and helper.values['az'] == '1.0'
    assert helper.result().value == YAW_90
    press(helper, 'up', 'backspace', 'backspace', 'backspace', '0')  # A zero axis is no rotation.
    assert helper.result().value == IDENTITY


def test_x_y_z_w_is_normalised():
    helper = press(quat_helper(), 'right', 'right', '1', 'right', '1')
    assert [helper.values[f] for f in 'xyzw'] == ['0.0', '0.0', '1', '1']
    assert helper.result().value == YAW_90
    assert press(quat_helper(), 'right', 'right', 'right', '0').result().value == IDENTITY  # All zeros.


def test_first_key_replaces_then_backspace_edits():
    helper = press(quat_helper(), 'right', 'right', 'right', '2')
    assert helper.values['w'] == '2'
    press(helper, '5', 'backspace')
    assert helper.values['w'] == '2'
    press(helper, 'right', 'right', 'up', 'up', 'up', 'up', 'up')  # Moving stays within the fields.
    assert helper.cur == 0


def test_bad_numbers_make_no_value():
    helper = press(quat_helper(), 'tab', 'tab', 'x')
    assert helper.result() is None
    assert press(helper, 'backspace').result() is None  # Empty isn't zero.
    assert press(helper, *'inf').result() is None


def test_the_yaw_of_the_value_is_filled_in():
    helper = quat_helper(dict(YAW_90))
    assert helper.values['yaw'] == '90.0' and helper.values['roll'] == '0.0'


def test_tab_starts_the_mode_afresh():
    helper = press(quat_helper(), 'tab', 'tab', '4', '5', 'tab', 'shift+tab')
    assert helper.cur == 0 and not helper.dirty and helper.values['yaw'] == '45'
    assert press(helper, '9').values['yaw'] == '9'  # The first key replaces again.


# ---------- header ----------
def test_header_auto():
    helper = header_helper('auto')
    assert [mode.name for mode in helper.modes()] == ['auto', 'now', 'manual'] and helper.mode == 0
    assert helper.note() == 'empty header, stamped at send' and helper.fields() == ()
    assert helper.values['frame_id'] == 'map'
    assert helper.result() == ('auto', 'auto — stamped when sent')
    press(helper, '9')  # Nothing to type in auto.
    assert helper.result().value == 'auto'


def test_header_now():
    helper = header_helper({'stamp': 'now', 'frame_id': 'odom'})
    assert (helper.mode, helper.fields(), helper.note()) == (1, ('frame_id',), 'stamped at send, with a frame')
    assert helper.result() == ({'stamp': 'now', 'frame_id': 'odom'}, 'stamp: now · frame_id: odom')
    press(helper, *'map')
    assert helper.result().value == {'stamp': 'now', 'frame_id': 'map'}


def test_header_manual():
    helper = header_helper({'stamp': {'sec': 2, 'nanosec': 500000000}, 'frame_id': 'map'})
    assert (helper.mode, helper.fields(), helper.values['stamp']) == (2, ('frame_id', 'stamp'), '2.5')
    assert helper.result() == ({'stamp': {'sec': 2, 'nanosec': 500000000}, 'frame_id': 'map'},
                               'stamp: 2 s 500000000 ns · frame_id: map')
    press(helper, 'down', '-', '1')
    assert helper.result() is None
    press(helper, 'tab')  # manual -> auto
    assert helper.result().value == 'auto'


def test_header_values_go_through_the_row():
    form = FieldRows(message_structure('msg', 'geometry_msgs/msg/PoseStamped'), pose())
    for text, value in (('auto', 'auto'), ('{stamp: now, frame_id: map}', {'stamp': 'now', 'frame_id': 'map'})):
        assert form.accept(0, text)[1] == value


# ---------- time ----------
def test_time_modes():
    goal = rows('tf2_msgs/action/LookupTransform', kind='action')
    helper = Helper.open(goal['source_time'])
    assert [mode.name for mode in helper.modes()] == ['now', 'seconds', 'sec + nanosec'] and helper.mode == 1
    assert helper.result() == ({'sec': 0, 'nanosec': 0}, 'sec: 0 · nanosec: 0')
    press(helper, *'2.5')
    assert helper.result().value == {'sec': 2, 'nanosec': 500000000}
    press(helper, 'tab', '7', 'down', '9')
    assert helper.result() == ({'sec': 7, 'nanosec': 9}, 'sec: 7 · nanosec: 9')
    press(helper, *'000000000')
    assert helper.result() is None  # nanosec stays under a second.
    press(helper, 'tab')
    assert helper.result() == ('now', 'now — stamped when sent')


# ---------- enum ----------
def test_enum_options():
    status = rows('diagnostic_msgs/msg/DiagnosticStatus', {'level': 2})
    helper = Helper.open(status['level'])
    assert helper.choices == LEVELS and helper.cur == 2 and helper.modes() == ()
    assert helper.keys() == 'j k or ↑↓ pick · 0–3 jump · enter applies · esc cancels'
    assert helper.result() == (2, '2  (ERROR)')
    assert press(helper, 'j', 'j').cur == 0 and press(helper, 'k').cur == 3 and press(helper, 'tab').cur == 0
    assert press(helper, 'down', 'up', 'shift+tab').cur == 3
    assert press(helper, '1').result() == (1, '1  (WARN)')
    assert press(helper, '7').cur == 1  # No option 7.
    assert Helper(ENUM, choices=tuple((str(n), n) for n in range(12))).jump_keys() == '0–9'  # Digits jump.


@pytest.mark.parametrize('typed, number', [('err', 2), ('ERROR', 2), ('w', 1), ('Stale', 3), ('3', 3), (' ok ', 0),
                                           ('7', 7)])
def test_enum_names_and_prefixes(typed, number):
    assert enum_value(LEVELS, 'level', typed) == number


def test_enum_error_names_the_choices():
    with pytest.raises(ValueError) as error:
        enum_value(LEVELS, 'level', 'hot')
    assert str(error.value) == 'level needs OK / WARN / ERROR / STALE or a number, got "hot"'
    with pytest.raises(ValueError):
        enum_value(LEVELS, 'level', '')


def test_enum_completion():
    assert enum_matches(LEVELS, '') == 'OK=0  WARN=1  ERROR=2  STALE=3 · type a name or number'
    assert enum_matches(LEVELS, 'er') == 'ERROR=2 · type a name or number'
    assert enum_matches(LEVELS, '1') == 'WARN=1 · type a name or number'
    assert enum_matches(LEVELS, 'x') == 'no match · type a name or number'


def test_an_enum_row_takes_a_name():
    form = FieldRows(message_structure('msg', 'diagnostic_msgs/msg/DiagnosticStatus'), {})
    assert form.accept(0, 'err') == (0, 2) and form.row(0).enum_name == 'ERROR'


# ---------- in the editors ----------
def entry_nav(*keys, bridge=None):
    bridge = bridge or FakeBridge.demo()
    nav = NavState(entry_router(bridge), clock=bridge.now)
    nav.set_catalog(bridge.latest_graph, {name: 1 for name in bridge.feeds})  # Published topics open in Echo.
    for key in keys:
        nav.handle_key(key)
    return nav


def editor(nav, tab=None):
    tab = tab or nav.tab
    return nav.provider.for_tab(tab).data(tab).editor


GOAL_POSE_ORIENTATION = ['/', *'goal', 'enter', 'enter', 'j', 'j', 'j']  # pose starts unfolded.


def test_the_popup_goes_under_the_row_where_it_is_drawn():
    """Header, toolbar, the panel's border and title, then rows 0–3; a short panel scrolls the row up."""
    nav = entry_nav(*GOAL_POSE_ORIENTATION)
    assert row_line(nav, 120, 30) == 7
    assert row_line(nav, 120, 7) == 5  # Room for two rows: rows 2 and 3 show.
    nav.handle_key('0')
    assert row_line(nav, 120, 30) is None


def test_f_yaw_90_enter_fills_the_row_and_u_undoes_it():
    nav = entry_nav(*GOAL_POSE_ORIENTATION)
    assert nav.footer().helper == 'Quaternion'
    nav.handle_key('f')
    assert nav.helper.kind == QUAT and nav.mode_name() == 'helper' and nav.footer().helper == ''
    assert nav.log[0] == ('f', 'opened the Quaternion helper for pose.orientation')
    for key in ['tab', 'tab', '9', '0', 'enter']:
        nav.handle_key(key)
    assert nav.helper is None and nav.layer == AREA and nav.row_index() == 3
    assert editor(nav).get(('pose', 'orientation')) == YAW_90
    assert nav.log[0] == ('enter', 'filled pose.orientation = {x: 0.0, y: 0.0, z: 0.707107, w: 0.707107} (u undoes)')
    nav.handle_key('u')
    assert editor(nav).get(('pose', 'orientation')) == IDENTITY
    assert nav.log[0] == ('u', 'undid the Quaternion helper on pose.orientation on /goal_pose')


def test_esc_changes_nothing():
    nav = entry_nav(*GOAL_POSE_ORIENTATION, 'f', 'tab', '4', '5', 'escape')
    assert nav.helper is None and editor(nav).get(('pose', 'orientation')) == IDENTITY
    assert nav.log[0] == ('esc', 'helper closed, nothing changed')
    nav.handle_key('u')
    assert nav.log[0] == ('u', 'nothing to undo here')


def test_a_helper_without_a_value_stays_open():
    nav = entry_nav(*GOAL_POSE_ORIENTATION, 'f', 'x', 'enter')
    assert nav.helper is not None and nav.toast.text == 'fix the highlighted values first'


def test_the_same_value_is_no_undo_step():
    nav = entry_nav(*GOAL_POSE_ORIENTATION, 'f', 'enter')
    assert nav.log[0] == ('enter', 'filled pose.orientation = {x: 0.0, y: 0.0, z: 0.0, w: 1.0}')
    assert not nav.undo_stack


def test_f_from_the_area_pick_goes_in_first():
    nav = entry_nav('/', *'goal', 'enter', 'f')
    assert nav.layer == AREA and nav.helper.kind == HEADER
    nav.handle_key('tab')
    nav.handle_key('enter')
    assert editor(nav).get(('header',)) == {'stamp': 'now', 'frame_id': 'map'}


def test_f_on_a_row_without_a_helper():
    nav = entry_nav('/', *'goal', 'enter', 'enter', 'j', 'f')
    assert nav.helper is None and nav.toast.text == 'no helper for this field — fields with one show [f …]'
    assert nav.log[0] == ('f', 'no helper on this field')


def test_enum_in_a_topic_message():
    nav = entry_nav('/', *'diag', 'enter', 'e', 'f', 'j', 'j', 'enter')
    assert editor(nav).get(('level',)) == 2
    nav.handle_key('f')
    assert KeyRow('Helper', '0–3', 'jump / next field', '') in keys_now(nav)  # The real option count.
    nav.handle_key('escape')
    for key in ['i', 'backspace', 'w', 'escape']:
        nav.handle_key(key)
    assert editor(nav).get(('level',)) == 1 and nav.log[0] == ('esc', 'kept level = 1 (u undoes)')
    for key in ['c', *'hot', 'enter']:
        nav.handle_key(key)
    assert nav.layer == EDIT and nav.errline(nav.tab) == 'level needs OK / WARN / ERROR / STALE or a number, got "hot"'


def test_header_in_a_service_request():
    tab = Tab('services', CAMERA_INFO_SERVICE.name)
    nav = entry_nav('/', *'camera', 'enter', 'enter', 'j', bridge=camera_demo())
    assert nav.tab == tab and nav.footer().helper == 'Header'
    for key in ['f', 'tab', 'tab', 'down', *'2.5', 'enter']:
        nav.handle_key(key)
    assert editor(nav).get(('camera_info', 'header')) == {'stamp': {'sec': 2, 'nanosec': 500000000}, 'frame_id': 'map'}
    nav.handle_key('space')
    assert nav.provider.for_tab(tab).data(tab).call is not None  # The request built and went out.


def test_time_in_an_action_goal():
    bridge = FakeBridge.demo()
    bridge.latest_graph = replace(DEMO_GRAPH, actions=DEMO_GRAPH.actions + (LOOKUP,))
    nav = entry_nav('/', *'lookup', 'enter', 'enter', 'j', 'j', bridge=bridge)
    assert nav.tab == Tab('actions', LOOKUP.name) and nav.footer().helper == 'Time'
    for key in ['f', *'1.5', 'enter']:
        nav.handle_key(key)
    assert editor(nav).get(('source_time',)) == {'sec': 1, 'nanosec': 500000000}
    for key in ['f', 'shift+tab', 'enter']:
        nav.handle_key(key)
    assert editor(nav).get(('source_time',)) == 'now'


def test_echo_rows_have_no_helper():
    nav = entry_nav('/', *'diag', 'enter', 'enter')
    assert nav.footer().helper == ''
    nav.handle_key('f')
    assert nav.helper is None
