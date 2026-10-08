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

"""The service entry (ros_tui/ui/entries/service.py) and its field-row editor, without textual.

The nav model runs over the live demo world (FakeBridge.demo()); its clock only moves when a test
advances it, and without a `post` or `work` the entry applies answers and loads types in place.
"""

from dataclasses import replace

import pytest
from harness.fake_bridge import CAMERA_INFO_SERVICE, DEMO_GRAPH, SERVICE_DELAY_S, FakeBridge, camera_demo
from harness.live_world import live_nav, press
from ros_tui.ros.graph import InterfaceEntry
from ros_tui.ui.fields import FieldRows
from ros_tui.ui.nav import AREA, EDIT, IN, Tab

ADD = Tab('services', '/add_two_ints')
POSE = Tab('services', '/set_pose')
CAMERA = Tab('services', CAMERA_INFO_SERVICE.name)
OPEN_ADD = ['/', *'add', 'enter']
EDIT_A = OPEN_ADD + ['enter', 'enter']  # Into REQUEST, then edit a.
MYSTERY = InterfaceEntry('/mystery', ())  # The graph knows no type for it.


def data(nav, tab=ADD):
    return nav.entry(tab)


def fields(form: FieldRows):
    return [(row.field, row.text) for row in form.rows()]


def test_open_loads_the_request():
    nav, _ = live_nav(*OPEN_ADD)
    assert nav.tab == ADD and fields(data(nav).editor) == [('a', '0'), ('b', '0')]
    assert data(nav).call is None and nav.row_count() == 2
    assert nav.footer()[1:4] == (('tabs', '/add_two_ints'), 'tab row', 'into request')


def test_the_type_loads_in_a_worker():
    jobs = []
    nav, _ = live_nav(*OPEN_ADD, work=jobs.append)
    assert data(nav).editor is None and data(nav).loading and nav.row_count() == 0
    press(nav, '0', '/', *'add', 'enter')  # Going back while it loads doesn't load it twice.
    assert len(jobs) == 1
    jobs.pop()()
    assert fields(data(nav).editor) == [('a', '0'), ('b', '0')] and not data(nav).loading


def test_a_type_that_does_not_load_says_why():
    bridge = FakeBridge.demo()
    nav, _ = live_nav(bridge=bridge)
    services = bridge.latest_graph.services
    nav.set_catalog(replace(bridge.latest_graph, services=(replace(services[0], types=('nope_msgs/srv/Nope',)),
                                                           *services[1:])))
    press(nav, *OPEN_ADD, 'space')
    assert data(nav).editor is None and 'nope_msgs/srv/Nope' in data(nav).error
    assert nav.feedback.toast.text.startswith('could not load nope_msgs/srv/Nope') and bridge.service_calls == []


@pytest.mark.parametrize('kind', ['topics', 'services', 'actions'])
def test_an_entry_without_a_type_says_so(kind):
    """Any message entry (topic, service, action) opens without a type, and sends nothing."""
    bridge = FakeBridge.demo()
    bridge.latest_graph = replace(DEMO_GRAPH, **{kind: getattr(DEMO_GRAPH, kind) + (MYSTERY,)})
    nav, _ = live_nav('/', *'myst', 'enter', 'space', bridge=bridge)
    assert nav.tab == Tab(kind, MYSTERY.name)
    assert nav.feedback.toast.text == 'no type information for this entry'
    assert bridge.service_calls == bridge.sent_goals == bridge.published == []


def test_edit_then_tab_to_the_next_field():
    nav, bridge = live_nav(*EDIT_A)
    assert (nav.layer, nav.editing.field, nav.editing.value) == (EDIT, 'a', '0')
    assert nav.editing.fresh  # A number that is still 0: the first key replaces it.
    press(nav, *'19', 'tab')
    assert (nav.layer, nav.editing.field, nav.row_index()) == (EDIT, 'b', 1)
    press(nav, *'23', 'escape')
    assert nav.layer == AREA and fields(data(nav).editor) == [('a', '19'), ('b', '23')]
    assert nav.feedback.log[0] == ('esc', 'kept b = 23 (u undoes)')
    assert bridge.service_calls == []  # Nothing is sent before space.


def test_a_bad_value_stays_in_insert_and_esc_drops_it():
    nav, _ = live_nav(*EDIT_A, *'abc', 'enter')
    assert nav.layer == EDIT and nav.feedback.errline(ADD) == 'a needs a whole number, got "abc"'
    assert nav.feedback.activity[0].text == '✗ a needs a whole number, got "abc"' and nav.feedback.activity[0].cls == 'r'
    press(nav, 'escape')
    assert nav.layer == AREA and fields(data(nav).editor)[0] == ('a', '0')
    assert nav.summary()['toast'] == ['a needs a whole number, got "abc" — kept the old value', 'bad']
    assert nav.feedback.errline(ADD) == ''


def test_space_calls_and_the_response_comes_back():
    nav, bridge = live_nav(*EDIT_A, *'19', 'tab', *'23', 'escape', 'space')
    (name, type_name, request), = bridge.service_calls
    assert (name, type_name, request.a, request.b) == ('/add_two_ints', 'example_interfaces/srv/AddTwoInts', 19, 23)
    assert nav.feedback.activity[0].text == '▶ called · a: 19, b: 23' and nav.feedback.activity[0].cls == 'c'
    assert nav.feedback.log[0] == ('space', 'calling /add_two_ints')
    call = data(nav).call
    assert not call.done and data(nav).response is None
    bridge.clock.advance(SERVICE_DELAY_S)
    assert call.done and call.elapsed_ms == SERVICE_DELAY_S * 1000 and call.error == ''
    assert fields(data(nav).response) == [('sum', '42')]
    assert nav.feedback.activity[0].text == '✓ response · sum: 42 (50.0 ms)' and nav.feedback.activity[0].cls == 'g'


def test_one_call_at_a_time():
    nav, bridge = live_nav(*OPEN_ADD, 'space', 'space')
    assert len(bridge.service_calls) == 1
    assert nav.summary()['toast'] == ['still calling /add_two_ints — wait for the response', 'bad']
    bridge.clock.advance(SERVICE_DELAY_S)
    press(nav, 'space')
    assert len(bridge.service_calls) == 2


def test_ctrl_s_in_insert_keeps_the_value_and_calls():
    nav, bridge = live_nav(*EDIT_A, '7', 'ctrl+s')
    assert nav.layer == AREA and bridge.service_calls[0][2].a == 7


def test_a_failed_call():
    bridge = FakeBridge.demo()
    bridge.failing_services['/add_two_ints'] = 'service /add_two_ints not available'
    nav, _ = live_nav(*OPEN_ADD, 'space', bridge=bridge)
    bridge.clock.advance(SERVICE_DELAY_S)
    assert data(nav).call.error == 'service /add_two_ints not available' and data(nav).response is None
    assert nav.feedback.activity[0].text == '✗ call failed: service /add_two_ints not available (50.0 ms)'
    assert nav.feedback.activity[0].cls == 'r'


def test_teleport_absolute_has_an_empty_response():
    nav, bridge = live_nav('/', *'set_pose', 'enter', 'enter', 'enter', '5', 'escape')
    assert nav.tab == POSE and fields(data(nav, POSE).editor) == [('x', '5.0'), ('y', '0.0'), ('theta', '0.0')]
    press(nav, 'space')
    bridge.clock.advance(SERVICE_DELAY_S)
    assert bridge.service_calls[0][2].x == 5.0
    assert data(nav, POSE).response.rows() == []
    assert nav.feedback.activity[0].text == '✓ response (50.0 ms)'


def test_history_steps_through_sends_and_back_to_the_draft():
    nav, bridge = live_nav(*OPEN_ADD, '[')
    assert (nav.feedback.toast.text, nav.feedback.log[0]) == ('send something first', ('[', 'no history for this entry yet'))
    press(nav, 'enter', 'enter', *'19', 'escape', 'space')
    bridge.clock.advance(SERVICE_DELAY_S)
    press(nav, 'enter', 'backspace', 'backspace', '5', 'escape', 'space')
    bridge.clock.advance(SERVICE_DELAY_S)
    press(nav, 'enter', 'backspace', '7', 'escape')  # The draft: a = 7.
    editor = data(nav).editor
    press(nav, '[')
    assert fields(editor)[0] == ('a', '5') and data(nav).hpos == 0
    assert nav.feedback.log[0] == ('[', 'loaded send 1 of 2 (1 = newest) · ] goes newer')
    press(nav, '[')
    assert fields(editor)[0] == ('a', '19')
    press(nav, '[')
    assert nav.summary()['toast'] == ['that was the oldest send', 'info'] and fields(editor)[0] == ('a', '19')
    press(nav, ']', ']')
    assert fields(editor)[0] == ('a', '7') and nav.feedback.log[0] == (']', 'back to your own edit')


def test_history_skips_the_send_the_editor_already_shows():
    nav, bridge = live_nav(*OPEN_ADD, 'space')
    bridge.clock.advance(SERVICE_DELAY_S)
    press(nav, 'enter', 'enter', '4', 'escape', 'space')
    bridge.clock.advance(SERVICE_DELAY_S)
    press(nav, '[')
    assert fields(data(nav).editor)[0] == ('a', '0') and data(nav).hpos == 1


def test_undo_only_in_this_tab():
    nav, _ = live_nav(*EDIT_A, '4', 'escape', '0', 'g', 'g', 'enter')  # Changed a, then opened /chatter.
    press(nav, 'u')
    assert nav.feedback.log[0] == ('u', 'nothing to undo here')
    press(nav, '1', 'u')
    assert fields(data(nav).editor)[0] == ('a', '0') and nav.feedback.log[0] == ('u', 'undid the edit of a on /add_two_ints')


def test_edits_stay_with_their_entry():
    nav, _ = live_nav(*EDIT_A, '4', 'escape', '/', *'set_pose', 'enter', '1')
    assert nav.tab == ADD and fields(data(nav).editor)[0] == ('a', '4')


def camera_nav(*keys):
    return live_nav('/', *'camera', 'enter', *keys, bridge=camera_demo())


def test_fold_and_unfold_keys():
    nav, _ = camera_nav('enter', 'j', 'j')
    assert nav.entry(CAMERA).form(nav.area()).row(2).field == 'camera_info.height'
    press(nav, 'h')
    assert nav.row_index() == 0 and nav.feedback.log[0] == ('h', 'up to camera_info')
    assert nav.footer().enter == 'fold'
    press(nav, 'h')
    assert nav.row_count() == 1 and nav.footer().enter == 'unfold' and nav.feedback.log[0] == ('h', 'folded camera_info')
    press(nav, 'h')
    assert nav.feedback.log[0] == ('h', 'already at the top — esc goes back up')
    press(nav, 'enter')
    assert nav.row_count() == 12 and nav.layer == AREA
    press(nav, 'l')
    assert nav.row_index() == 1 and nav.feedback.log[0] == ('l', 'into camera_info')
    press(nav, 'l')
    assert nav.feedback.log[0] == ('l', 'nothing to unfold here')
    press(nav, 'escape')
    assert nav.layer == IN  # esc is always up one layer, however deep the row.


def test_enter_folds_a_list_and_i_types_it_whole():
    """enter does what the footer says on a list of numbers (unfold / fold); i edits it as one value."""
    nav, _ = camera_nav('enter', *['j'] * 6)
    editor = data(nav, CAMERA).editor
    assert editor.row(6).field == 'camera_info.k' and nav.footer().enter == 'unfold'
    press(nav, 'enter')
    assert nav.layer == AREA and editor.row(6).open and nav.footer().enter == 'fold'
    press(nav, 'i')
    assert nav.layer == EDIT and nav.editing.value == '[' + ', '.join(['0.0'] * 9) + ']'


def test_add_edit_delete_and_undo_list_elements():
    nav, _ = camera_nav('enter', *['j'] * 5)
    editor = data(nav, CAMERA).editor
    assert editor.row(5).field == 'camera_info.d'
    press(nav, 'o')
    assert nav.layer == EDIT and nav.editing.field == 'camera_info.d[0]'
    press(nav, *'0.1', 'enter', 'o', *'0.2', 'enter')
    assert editor.get(('camera_info', 'd')) == [0.1, 0.2] and nav.row_index() == 7
    press(nav, 'k', 'd')
    assert editor.get(('camera_info', 'd')) == [0.2] and nav.feedback.log[0] == ('d', 'deleted camera_info.d[0] (u undoes)')
    press(nav, 'u')
    assert editor.get(('camera_info', 'd')) == [0.1, 0.2]
    assert nav.feedback.log[0] == ('u', f'undid deleting camera_info.d[0] on {CAMERA.name}')
    press(nav, 'j', 'j', 'o')  # On k, a fixed array: nothing changes.
    assert (nav.feedback.toast.text, nav.layer) == ('camera_info.k always has 9 elements', AREA)
    press(nav, 'g', 'g', 'd')
    assert nav.feedback.toast.text == 'd deletes a list element — move the cursor to one ([0], [1] …)'


def test_every_leaf_of_a_nested_request_is_reached_and_edited_by_keys():
    """Walk the request with j, unfold with l, add a list element with o; every field that holds a
    value is edited (i) and kept (esc) on the way."""
    nav, _ = camera_nav('enter')
    editor = data(nav, CAMERA).editor
    edited = []
    while True:
        row = editor.row(nav.row_index())
        if row.field == 'camera_info.d' and not row.value:
            press(nav, 'o', 'escape', 'k')  # Give the empty list an element, then back to its row.
            continue
        if row.folds and not row.open:
            press(nav, 'l')
        if row.editable:
            press(nav, 'i')
            assert nav.layer == EDIT and nav.editing.field == row.field
            press(nav, 'escape')
            assert nav.layer == AREA
            edited.append(row.field)
        before = nav.row_index()
        press(nav, 'j')
        if nav.row_index() == before:
            break
    rows = editor.rows()
    assert all(row.open for row in rows if row.folds)  # Everything is unfolded now …
    assert edited == [row.field for row in rows if row.editable]  # … and every value was edited.
    assert {'camera_info.header', 'camera_info.d[0]', 'camera_info.k[8]', 'camera_info.roi.do_rectify'} <= set(edited)


def test_a_send_check_error_goes_to_its_row():
    nav, bridge = camera_nav('enter')
    editor = data(nav, CAMERA).editor
    editor.values['camera_info']['roi']['x_offset'] = -1  # Behind the editor's back: only the send check sees it.
    press(nav, 'escape', 'space')
    assert bridge.service_calls == []
    assert nav.feedback.errline(CAMERA) == 'camera_info.roi.x_offset must be an unsigned integer in [0, 4294967295]'
    assert nav.summary()['toast'] == ['fix the highlighted values first', 'bad']
    msg = nav.entry(CAMERA).area_named('msg')
    assert editor.row(nav.row_index(msg)).field == 'camera_info.roi.x_offset' and editor.bad == 'camera_info.roi.x_offset'
    press(nav, 'enter', 'c', '3', 'enter', 'space')
    assert editor.bad == '' and len(bridge.service_calls) == 1


def test_the_response_has_rows_too():
    nav, bridge = camera_nav('space')
    bridge.clock.advance(SERVICE_DELAY_S)
    assert fields(data(nav, CAMERA).response) == [('success', 'true'), ('status_message', "'stored'")]
    assert nav.feedback.activity[0].text == "✓ response · success: true, status_message: stored (50.0 ms)"
    press(nav, 'l', 'enter')
    assert nav.layer == AREA and nav.area().id == 'out' and nav.row_count() == 2
