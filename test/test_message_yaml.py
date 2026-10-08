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

"""Pure unit tests for checked YAML <-> message conversion (no rclpy init, no UI)."""

import math

import pytest
import yaml
from ros_tui.ros.message_yaml import (
    FieldError,
    IntrospectionError,
    build_message,
    import_type,
    interface_label,
    message_structure,
    message_to_plain,
    request_class,
)

ROUNDTRIP_TYPES = [
    ('msg', 'std_msgs/msg/String'),
    ('msg', 'std_msgs/msg/Bool'),
    ('msg', 'std_msgs/msg/Float64'),
    ('msg', 'std_msgs/msg/UInt8'),
    ('msg', 'std_msgs/msg/Char'),
    ('msg', 'std_msgs/msg/Byte'),
    ('msg', 'std_msgs/msg/UInt8MultiArray'),
    ('msg', 'std_msgs/msg/Header'),
    ('msg', 'geometry_msgs/msg/PoseStamped'),
    ('msg', 'geometry_msgs/msg/PoseWithCovarianceStamped'),
    ('msg', 'geometry_msgs/msg/Polygon'),
    ('msg', 'geometry_msgs/msg/Twist'),
    ('msg', 'sensor_msgs/msg/JointState'),
    ('msg', 'sensor_msgs/msg/PointCloud2'),
    ('msg', 'sensor_msgs/msg/Image'),
    ('msg', 'builtin_interfaces/msg/Time'),
    ('msg', 'builtin_interfaces/msg/Duration'),
    ('msg', 'test_msgs/msg/Arrays'),
    ('msg', 'test_msgs/msg/BoundedSequences'),
    ('msg', 'test_msgs/msg/UnboundedSequences'),
    ('msg', 'test_msgs/msg/WStrings'),
    ('msg', 'test_msgs/msg/Nested'),
    ('msg', 'test_msgs/msg/Defaults'),
    ('srv', 'example_interfaces/srv/AddTwoInts'),
    ('srv', 'std_srvs/srv/SetBool'),
    ('action', 'example_interfaces/action/Fibonacci'),
    ('action', 'test_msgs/action/NestedMessage'),
]


def seed(kind: str, type_name: str) -> dict:
    """What an editor starts from: the default message as plain data, a nested Header as 'auto'."""
    return message_to_plain(request_class(kind, import_type(kind, type_name))(), seed=True)


@pytest.mark.parametrize(('kind', 'type_name'), ROUNDTRIP_TYPES)
def test_default_seed_round_trips(kind, type_name):
    values = seed(kind, type_name)
    fillable = request_class(kind, import_type(kind, type_name))
    message, time_setters = build_message(fillable, values)
    if 'auto' in values.values():
        # A nested header seeds as the 'auto' magic value: it builds cleanly but leaves a
        # deferred stamp setter, so it does not round-trip to the same plain dict.
        assert time_setters
    else:
        assert time_setters == []
        assert message_to_plain(message) == values


def test_nested_header_seeds_as_auto():
    assert seed('msg', 'geometry_msgs/msg/PoseStamped')['header'] == 'auto'
    # A top-level Header topic has no nested header field, so it stays expanded.
    assert seed('msg', 'std_msgs/msg/Header') == {'stamp': {'sec': 0, 'nanosec': 0}, 'frame_id': ''}


def test_unknown_type_raises_introspection_error():
    with pytest.raises(IntrospectionError, match='not_a_pkg'):
        import_type('msg', 'not_a_pkg/msg/Nope')


def test_interface_label():
    assert interface_label(import_type('msg', 'geometry_msgs/msg/Pose')) == 'geometry_msgs/msg/Pose'


def test_empty_request_seed_and_build():
    trigger = import_type('srv', 'std_srvs/srv/Trigger')
    assert seed('srv', 'std_srvs/srv/Trigger') == {}
    message, time_setters = build_message(trigger.Request, {})
    assert time_setters == []
    assert message == trigger.Request()


def test_uint8_out_of_range_rejected_with_range_text():
    uint8_class = import_type('msg', 'std_msgs/msg/UInt8')
    with pytest.raises(FieldError) as excinfo:
        build_message(uint8_class, {'data': 300})
    assert excinfo.value.path == 'data'
    assert '[0, 255]' in excinfo.value.detail


def test_float32_overflow_rejected():
    float32_class = import_type('msg', 'std_msgs/msg/Float32')
    with pytest.raises(FieldError) as excinfo:
        build_message(float32_class, {'data': 1e40})
    assert excinfo.value.path == 'data'
    assert 'float' in excinfo.value.detail


def test_fixed_array_wrong_length_rejected_with_path():
    stamped_class = import_type('msg', 'geometry_msgs/msg/PoseWithCovarianceStamped')
    with pytest.raises(FieldError) as excinfo:
        build_message(stamped_class, {'pose': {'covariance': [0.0, 0.0]}})
    assert excinfo.value.path == 'pose.covariance'
    assert '36' in excinfo.value.detail


def test_fixed_int_array_out_of_range_rejected():
    # numpy.array() would silently wrap 300 into a uint8 on numpy < 2 — must be caught.
    arrays_class = import_type('msg', 'test_msgs/msg/Arrays')
    with pytest.raises(FieldError) as excinfo:
        build_message(arrays_class, {'uint8_values': [300, 0, 0]})
    assert excinfo.value.path == 'uint8_values[0]'
    assert '[0, 255]' in excinfo.value.detail


def test_fixed_int_array_rejects_fractional_float():
    arrays_class = import_type('msg', 'test_msgs/msg/Arrays')
    with pytest.raises(FieldError) as excinfo:
        build_message(arrays_class, {'int32_values': [1.5, 0, 0]})
    assert excinfo.value.path == 'int32_values[0]'


def test_fixed_float_array_accepts_ints():
    arrays_class = import_type('msg', 'test_msgs/msg/Arrays')
    message, _ = build_message(arrays_class, {'float64_values': [1, 2, 3]})
    assert message_to_plain(message)['float64_values'] == [1.0, 2.0, 3.0]


def test_fixed_float32_array_overflow_rejected():
    arrays_class = import_type('msg', 'test_msgs/msg/Arrays')
    with pytest.raises(FieldError) as excinfo:
        build_message(arrays_class, {'float32_values': [1e40, 0.0, 0.0]})
    assert excinfo.value.path == 'float32_values[0]'
    assert 'float' in excinfo.value.detail


def test_bounded_sequence_overflow_rejected():
    bounded_class = import_type('msg', 'test_msgs/msg/BoundedSequences')
    with pytest.raises(FieldError) as excinfo:
        build_message(bounded_class, {'bool_values': [True, False, True, False]})
    assert excinfo.value.path == 'bool_values'
    assert '3' in excinfo.value.detail


def test_nested_error_carries_dotted_path():
    pose_stamped_class = import_type('msg', 'geometry_msgs/msg/PoseStamped')
    with pytest.raises(FieldError) as excinfo:
        build_message(pose_stamped_class, {'pose': {'position': {'x': 'oops'}}})
    assert excinfo.value.path == 'pose.position.x'
    assert 'oops' in excinfo.value.detail


def test_array_of_messages_error_carries_index_path():
    polygon_class = import_type('msg', 'geometry_msgs/msg/Polygon')
    with pytest.raises(FieldError) as excinfo:
        build_message(polygon_class, {'points': [{'x': 1.0}, {'x': 'bad'}]})
    assert excinfo.value.path == 'points[1].x'


def test_unknown_field_rejected_with_type_name():
    pose_class = import_type('msg', 'geometry_msgs/msg/Pose')
    with pytest.raises(FieldError) as excinfo:
        build_message(pose_class, {'bogus_field': 1})
    assert excinfo.value.path == 'bogus_field'
    assert 'geometry_msgs/msg/Pose' in excinfo.value.detail


def test_scalar_where_mapping_expected_rejected():
    pose_stamped_class = import_type('msg', 'geometry_msgs/msg/PoseStamped')
    with pytest.raises(FieldError) as excinfo:
        build_message(pose_stamped_class, {'pose': 'oops'})
    assert excinfo.value.path == 'pose'
    assert 'mapping' in excinfo.value.detail


def test_list_field_rejects_non_list():
    joint_state_class = import_type('msg', 'sensor_msgs/msg/JointState')
    with pytest.raises(FieldError) as excinfo:
        build_message(joint_state_class, {'name': 'notalist'})
    assert excinfo.value.path == 'name'
    assert 'expected a list' in excinfo.value.detail


def test_byte_accepts_int_and_never_zero_fills():
    byte_class = import_type('msg', 'std_msgs/msg/Byte')
    message, _ = build_message(byte_class, {'data': 3})
    assert message.data == b'\x03'
    assert message_to_plain(message) == {'data': 3}


def test_byte_out_of_range_rejected():
    byte_class = import_type('msg', 'std_msgs/msg/Byte')
    with pytest.raises(FieldError) as excinfo:
        build_message(byte_class, {'data': 300})
    assert '[0, 255]' in excinfo.value.detail


def test_char_round_trips_as_int():
    char_class = import_type('msg', 'std_msgs/msg/Char')
    message, _ = build_message(char_class, {'data': 65})
    assert message_to_plain(message) == {'data': 65}


def test_nan_and_inf_round_trip():
    float64_class = import_type('msg', 'std_msgs/msg/Float64')
    nan_message, _ = build_message(float64_class, yaml.safe_load('data: .nan'))
    assert math.isnan(nan_message.data)
    inf_message, _ = build_message(float64_class, yaml.safe_load('data: -.inf'))
    assert inf_message.data == float('-inf')
    # Bare strings coerce through float() like upstream set_message_fields.
    bare_message, _ = build_message(float64_class, {'data': 'nan'})
    assert math.isnan(bare_message.data)


def test_int_literal_into_float_field_coerced():
    pose_class = import_type('msg', 'geometry_msgs/msg/Pose')
    message, _ = build_message(pose_class, {'position': {'x': 5}})
    assert message.position.x == 5.0


def test_time_now_magic_returns_deferred_setter():
    pose_stamped_class = import_type('msg', 'geometry_msgs/msg/PoseStamped')
    time_class = import_type('msg', 'builtin_interfaces/msg/Time')
    message, time_setters = build_message(pose_stamped_class, {'header': {'stamp': 'now'}})
    assert len(time_setters) == 1
    time_setters[0](time_class(sec=5, nanosec=7))
    assert message.header.stamp.sec == 5
    assert message.header.stamp.nanosec == 7


def test_header_auto_magic_returns_deferred_setter():
    pose_stamped_class = import_type('msg', 'geometry_msgs/msg/PoseStamped')
    time_class = import_type('msg', 'builtin_interfaces/msg/Time')
    message, time_setters = build_message(pose_stamped_class, {'header': 'auto'})
    assert len(time_setters) == 1
    time_setters[0](time_class(sec=9))
    assert message.header.stamp.sec == 9
    assert message.header.frame_id == ''


def test_wstring_unicode_round_trips():
    wstrings_class = import_type('msg', 'test_msgs/msg/WStrings')
    message, _ = build_message(wstrings_class, {'wstring_value': 'ハローワールド'})
    assert message_to_plain(message)['wstring_value'] == 'ハローワールド'


def test_array_of_messages_with_partial_dicts():
    polygon_class = import_type('msg', 'geometry_msgs/msg/Polygon')
    message, _ = build_message(polygon_class, {'points': [{'x': 4.0}]})
    assert message.points[0].x == 4.0
    assert message.points[0].y == 0.0


def test_build_from_none_returns_defaults():
    string_class = import_type('msg', 'std_msgs/msg/String')
    message, time_setters = build_message(string_class, None)
    assert message == string_class()
    assert time_setters == []


def test_message_structure_scalar_leaf():
    fields = message_structure('msg', 'std_msgs/msg/String')
    assert len(fields) == 1
    assert fields[0].name == 'data'
    assert fields[0].type_label == 'string'
    assert fields[0].children == ()


def test_message_structure_nested_and_labels():
    fields = {node.name: node for node in message_structure('msg', 'geometry_msgs/msg/PoseStamped')}
    assert fields['header'].children  # std_msgs/Header expands.
    pose = fields['pose']
    child_names = [child.name for child in pose.children]
    assert child_names == ['position', 'orientation']
    # Leaf type labels match the raw get_fields_and_field_types() strings.
    position = next(child for child in pose.children if child.name == 'position')
    x_field = next(child for child in position.children if child.name == 'x')
    assert x_field.type_label == 'double'


def test_message_structure_walks_into_array_element_type():
    fields = {node.name: node for node in message_structure('msg', 'geometry_msgs/msg/Polygon')}
    points = fields['points']  # geometry_msgs/Point32[]
    assert points.children  # walks into the array's element message, not treated as scalar.
    assert any(child.name == 'x' for child in points.children)


def test_message_structure_enum_constants_sole_integer_field():
    # DiagnosticStatus: un-prefixed byte constants attach to the only integer field, `level`,
    # in value order (not dir()'s alphabetical order), decoded from bytes to int.
    fields = {node.name: node for node in message_structure('msg', 'diagnostic_msgs/msg/DiagnosticStatus')}
    assert fields['level'].constants == (('OK', 0), ('WARN', 1), ('ERROR', 2), ('STALE', 3))
    assert fields['name'].constants == ()  # a string field carries no enum choices.


def test_message_structure_enum_constants_prefix_grouped():
    # BatteryState: each integer field gets only its own POWER_SUPPLY_<FIELD>_* prefix group.
    fields = {node.name: node for node in message_structure('msg', 'sensor_msgs/msg/BatteryState')}
    status = dict(fields['power_supply_status'].constants)
    assert status and all(name.startswith('POWER_SUPPLY_STATUS_') for name in status)
    assert not any(name.startswith('POWER_SUPPLY_HEALTH_') for name in status)
