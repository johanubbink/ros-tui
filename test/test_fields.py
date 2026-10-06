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

"""The field-row model (ros_tui/ui/fields.py) over real message structures, without textual."""

import functools
import subprocess
import sys
from pathlib import Path

import pytest
from ros_tui.ros.message_yaml import build_message, import_type, message_structure, message_to_plain, request_class
from ros_tui.ui.fields import (ARRAY, COMPACT, LEAF, MESSAGE, Element, FieldRows, array_info, default_value, parse,
                               parse_path, path_text, short_type, summary)
from test_message_yaml import ROUNDTRIP_TYPES

REPO = Path(__file__).resolve().parents[1]


def form_for(kind, type_name, values=None):
    fillable = request_class(kind, import_type(kind, type_name))
    seed = message_to_plain(fillable(), seed=True) if values is None else values
    return FieldRows(message_structure(kind, type_name), seed), functools.partial(build_message, fillable)


def unfold_all(form):
    """Unfold every row that has something inside, the way l does, until nothing changes."""
    changed = True
    while changed:
        changed = False
        for index, row in enumerate(form.rows()):
            if row.folds and not row.open and form.unfold(index) and form.row(index).open:
                changed = True
                break


def rows_seen(form):
    return [(row.field, row.shape, row.text, row.hint) for row in form.rows()]


@pytest.mark.parametrize(('kind', 'type_name'), ROUNDTRIP_TYPES)
def test_rows_round_trip(kind, type_name):
    """rows -> dict -> rows: retyping every editable row's own text changes nothing, the plain
    values build, and rows rebuilt from them read the same."""
    form, validate = form_for(kind, type_name)
    seed = form.to_plain()
    unfold_all(form)
    for index, row in enumerate(form.rows()):
        if row.editable:
            old, new = form.accept(index, row.edit_text(), validate)
            assert new == old, row.field
    assert form.to_plain() == seed
    validate(form.to_plain())
    again, _ = form_for(kind, type_name, form.to_plain())
    unfold_all(again)
    assert rows_seen(again) == rows_seen(form)


def test_compact_types_are_one_row():
    form, _ = form_for('msg', 'geometry_msgs/msg/PoseStamped')
    assert [(row.field, row.shape, row.text) for row in form.rows()] == [
        ('header', COMPACT, 'auto'), ('pose', MESSAGE, '{…}')]
    form.toggle(1)
    assert [(row.field, row.depth, row.text, row.hint) for row in form.rows()[2:]] == [
        ('pose.position', 1, '{x: 0.0, y: 0.0, z: 0.0}', 'Point'),
        ('pose.orientation', 1, '{x: 0.0, y: 0.0, z: 0.0, w: 1.0}', 'Quaternion')]


def test_a_single_nested_message_starts_unfolded():
    form, _ = form_for('srv', 'sensor_msgs/srv/SetCameraInfo')
    assert [row.field for row in form.rows()][:3] == ['camera_info', 'camera_info.header', 'camera_info.height']
    assert form.row(0).open


def test_fold_unfold_and_up_to_the_parent():
    form, _ = form_for('msg', 'geometry_msgs/msg/PoseStamped')
    assert form.unfold(0) is None  # header is a compact row: nothing inside it.
    assert form.unfold(1) == (1, 'unfolded pose') and form.row(1).open
    assert form.unfold(1) == (2, 'into pose')
    assert form.fold(3) == (1, 'up to pose')  # h on a field goes to its parent …
    assert form.fold(1) == (1, 'folded pose') and len(form.rows()) == 2  # … and h there folds it.
    assert form.fold(0) is None  # Top level: nothing above.
    assert form.toggle(0) is None and form.toggle(1) == 'unfolded pose' and form.toggle(1) == 'folded pose'


def test_arrays_add_and_delete():
    form, validate = form_for('msg', 'geometry_msgs/msg/Polygon')
    assert rows_seen(form) == [('points', ARRAY, '[0 items]', 'Point32[]')]
    assert form.toggle(0) == 'points is empty — o adds an element'
    assert form.add_item(0) == ('points', 0)  # On the list's own row: at the end.
    assert form.add_item(1) == ('points', 1)  # On an element: after it.
    assert [(row.field, row.shape, row.text) for row in form.rows()] == [
        ('points', ARRAY, '[2 items]'),
        ('points[0]', COMPACT, '{x: 0.0, y: 0.0, z: 0.0}'), ('points[1]', COMPACT, '{x: 0.0, y: 0.0, z: 0.0}')]
    form.accept(1, '{x: 1.5}', validate)
    form.add_item(1)
    zero = '{x: 0.0, y: 0.0, z: 0.0}'
    assert [row.text for row in form.rows()[1:]] == ['{x: 1.5, y: 0.0, z: 0.0}', zero, zero]
    assert form.delete_item(1) == (('points', 0), ('points', 0))  # The next element moves up under the cursor.
    assert form.delete_item(2) == (('points', 1), ('points', 0))  # The last one: back to the one before.
    assert form.delete_item(1) == (('points', 0), ('points',))  # The only one: back to the list.
    assert form.to_plain() == {'points': []}
    with pytest.raises(ValueError, match='d deletes a list element'):
        form.delete_item(0)


def test_nested_lists_keep_their_folds_when_elements_move():
    form, _ = form_for('msg', 'diagnostic_msgs/msg/DiagnosticArray')
    form.add_item(1)
    form.add_item(2)  # status[0], status[1]
    form.toggle(form.index_of('status[1]'))
    assert form.row(form.index_of('status[1]')).open
    form.add_item(form.index_of('status[0]'))  # A new status[1]: the open one is status[2] now.
    assert form.row(form.index_of('status[2]')).open and not form.row(form.index_of('status[1]')).open
    form.delete_item(form.index_of('status[0]'))
    assert form.row(form.index_of('status[1]')).open


def test_fixed_and_bounded_lists():
    form, _ = form_for('msg', 'test_msgs/msg/BoundedSequences')
    row = form.index_of('bool_values')
    for _ in range(3):
        form.add_item(row)
    with pytest.raises(ValueError, match='bool_values holds at most 3 elements'):
        form.add_item(row)
    form, _ = form_for('msg', 'test_msgs/msg/Arrays')
    with pytest.raises(ValueError, match='bool_values always has 3 elements'):
        form.add_item(form.index_of('bool_values'))
    form.toggle(form.index_of('bool_values'))
    with pytest.raises(ValueError, match='always has 3 elements'):
        form.delete_item(form.index_of('bool_values[1]'))


def test_diagnostic_array_rows():
    form, validate = form_for('msg', 'diagnostic_msgs/msg/DiagnosticArray')
    assert rows_seen(form) == [('header', COMPACT, 'auto', 'Header'),
                               ('status', ARRAY, '[0 items]', 'DiagnosticStatus[]')]
    form.add_item(1)
    form.toggle(2)
    assert [(row.field, row.depth, row.shape, row.text, row.hint) for row in form.rows()[2:]] == [
        ('status[0]', 1, MESSAGE, '', 'DiagnosticStatus'),
        ('status[0].level', 2, LEAF, '0', 'octet'),
        ('status[0].name', 2, LEAF, "''", 'string'),
        ('status[0].message', 2, LEAF, "''", 'string'),
        ('status[0].hardware_id', 2, LEAF, "''", 'string'),
        ('status[0].values', 2, ARRAY, '[0 items]', 'KeyValue[]')]
    assert form.row(3).enum_name == 'OK'
    form.accept(3, '1', validate)
    assert form.row(3).enum_name == 'WARN'
    with pytest.raises(ValueError) as error:
        form.accept(3, '300', validate)
    assert str(error.value) == 'status[0].level must be an integer in [0, 255], got 300'
    form.add_item(form.index_of('status[0].values'))
    assert form.row(form.index_of('status[0].values[0]')).shape == MESSAGE
    validate(form.to_plain())


@pytest.mark.parametrize('label, text, value', [
    ('int64', '19', 19), ('int64', ' -3 ', -3), ('int64', '5.0', 5), ('uint8', '255', 255),
    ('double', '5', 5.0), ('double', '1e-3', 0.001), ('float', '-2.5', -2.5),
    ('boolean', 'TRUE', True), ('boolean', 'false', False),
    ('string', 'hello world', 'hello world'), ('string', "'quoted'", 'quoted'), ('string', '"42"', '42'),
    ('string', '42', '42'), ('string', '', ''), ('string<=5', 'abc', 'abc'),
])
def test_parse_a_value(label, text, value):
    row = leaf_row(label)
    parsed = parse(row, text)
    assert parsed == value and type(parsed) is type(value)


@pytest.mark.parametrize('label, text, message', [
    ('int64', 'abc', 'a needs a whole number, got "abc"'),
    ('int64', '2.5', 'a needs a whole number, got "2.5"'),
    ('int64', 'true', 'a needs a whole number, got "true"'),
    ('int64', '', 'a needs a whole number, got ""'),
    ('double', '5x', 'a needs a number, got "5x"'),
    ('boolean', '1', 'a needs true or false, got "1"'),
    ('double[3]', '7', 'a needs a list like [1, 2], got "7"'),
    ('double[3]', '[1, x]', 'a[1] needs a number, got "x"'),
])
def test_parse_errors_name_the_field(label, text, message):
    row = leaf_row(label)
    with pytest.raises(ValueError) as error:
        parse(row, text)
    assert str(error.value) == message


def test_compact_rows_parse_flow_maps():
    form, validate = form_for('msg', 'geometry_msgs/msg/PoseStamped')
    form.toggle(1)
    assert form.accept(2, '{x: 1, y: 2}', validate)[1] == {'x': 1.0, 'y': 2.0, 'z': 0.0}  # Merged, made floats.
    assert form.row(2).text == '{x: 1.0, y: 2.0, z: 0.0}'
    with pytest.raises(ValueError) as error:
        form.accept(2, '1, 2', validate)
    assert str(error.value) == 'pose.position needs {x: …, y: …, z: …}, got "1, 2"'
    with pytest.raises(ValueError) as error:
        form.accept(2, '{x: 1, q: 2}', validate)
    assert str(error.value) == "pose.position.q: 'q' is not a field of geometry_msgs/msg/Point"
    with pytest.raises(ValueError) as error:
        form.accept(0, 'later', validate)
    assert str(error.value) == 'header needs auto or {stamp: …, frame_id: …}, got "later"'
    assert form.accept(0, '{stamp: now, frame_id: map}', validate)[1] == {'stamp': 'now', 'frame_id': 'map'}
    message, setters = validate(form.to_plain())
    assert message.header.frame_id == 'map' and len(setters) == 1
    assert form.accept(0, 'auto', validate)[1] == 'auto'


def test_a_list_of_numbers_is_typed_whole():
    form, validate = form_for('msg', 'test_msgs/msg/Arrays')
    index = form.index_of('float64_values')
    assert form.row(index).editable and form.row(index).edit_text() == '[0.0, 0.0, 0.0]'
    assert form.accept(index, '[1, 2.5, 3]', validate)[1] == [1.0, 2.5, 3.0]
    with pytest.raises(ValueError) as error:
        form.accept(index, '[1, 2]', validate)
    assert 'float64_values' in str(error.value)


def test_send_check_errors_map_to_their_row():
    form, validate = form_for('msg', 'diagnostic_msgs/msg/DiagnosticArray')
    form.add_item(1)
    form.values['status'][0]['level'] = 999  # Set behind the editor's back: only the send check sees it.
    with pytest.raises(Exception) as error:
        validate(form.to_plain())
    assert error.value.path == 'status[0].level'
    form.toggle(1)
    assert [row.field for row in form.rows()] == ['header', 'status']  # Folded away.
    index = form.reveal(error.value.path)
    assert form.row(index).field == 'status[0].level'  # Unfolded to show it.
    form, _ = form_for('msg', 'geometry_msgs/msg/PoseStamped')
    assert form.row(form.reveal('pose.position.x')).field == 'pose.position'  # Inside a compact row.


def test_paths_hints_and_summaries():
    assert path_text(('points', 1, 'x')) == 'points[1].x' and parse_path('points[1].x') == ('points', 1, 'x')
    assert [short_type(label) for label in ('int64', 'geometry_msgs/Point', 'double[9]',
                                            'sequence<geometry_msgs/Point32>', 'sequence<double, 3>')] == [
        'int64', 'Point', 'double[9]', 'Point32[]', 'double[<=3]']
    assert array_info('sequence<string<=5, 3>') == ('string<=5', None, 3)
    assert summary({'a': 19, 'b': 23}, 60) == 'a: 19, b: 23'
    assert summary({'data': 'x' * 100}, 20) == 'data: xxxxxxxxxxxxx…'


def test_pure_python():
    """fields.py imports neither textual nor rclpy."""
    code = ('import sys; import ros_tui.ui.fields; '
            'print(sorted({m.split(".")[0] for m in sys.modules} & {"textual", "rclpy", "rich", "rosidl_runtime_py"}))')
    out = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == '[]'


def leaf_row(label):
    """The row of a message with one field `a` of type `label`, at its zero value."""
    node = Element('a', label)
    return FieldRows((node,), {'a': default_value(node)}).row(0)
