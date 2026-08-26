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

"""Unit tests for the pure text helpers behind the field wizards."""

import math

import pytest

from ros_tui.ros.message_yaml import FieldNode
from ros_tui.ui.field_wizards import (
    EnumWizardPopup,
    HeaderWizardPopup,
    QuaternionWizardPopup,
    TimeWizardPopup,
    _parse_header,
    _parse_time,
    clean_quat,
    cursor_field_path,
    epoch_to_stamp,
    field_block_range,
    field_type_at,
    matched_wizard,
    normalize_quat,
    parse_wallclock,
    quat_about_axis,
    quat_from_euler,
    render_field_block,
    replace_block,
    seconds_str_to_stamp,
    stamp_to_seconds_str,
)

try:
    import tf_transformations  # noqa: F401

    _HAS_TF = True
except ImportError:
    _HAS_TF = False

# quat_from_euler/quat_about_axis delegate to tf_transformations, which ships as a ROS package
# (apt), not on PyPI. Skip those cases where it's absent (local dev without ROS); they run in
# Docker/CI. The normalize/clean/registry cases below need no ROS and always run.
requires_tf = pytest.mark.skipif(not _HAS_TF, reason='tf_transformations not installed')

_SQRT_HALF = math.sqrt(0.5)  # ~0.70710678, the x/y/z/w magnitude for a 90-degree rotation.

# A PoseStamped-shaped structure: header (std_msgs/Header, itself nesting a Time stamp) +
# pose.{position,orientation}. The stamp child exercises innermost-wins wizard matching.
POSE_STAMPED = (
    FieldNode(
        'header',
        'std_msgs/Header',
        (
            FieldNode('stamp', 'builtin_interfaces/Time',
                      (FieldNode('sec', 'uint32'), FieldNode('nanosec', 'uint32'))),
            FieldNode('frame_id', 'string'),
        ),
    ),
    FieldNode(
        'pose',
        'geometry_msgs/Pose',
        (
            FieldNode('position', 'geometry_msgs/Point', (FieldNode('x', 'double'),)),
            FieldNode('orientation', 'geometry_msgs/Quaternion', (FieldNode('w', 'double'),)),
        ),
    ),
)

SEED = 'header: auto\npose:\n  position:\n    x: 0.0\n  orientation:\n    w: 1.0\n'


def test_cursor_field_path_top_level():
    assert cursor_field_path(SEED, 0) == ['header']


def test_cursor_field_path_nested():
    lines = SEED.splitlines()
    assert cursor_field_path(SEED, lines.index('  position:')) == ['pose', 'position']
    assert cursor_field_path(SEED, lines.index('    x: 0.0')) == ['pose', 'position', 'x']


def test_cursor_field_path_skips_comments_and_blanks():
    text = 'header: auto\n# constants: FOO=1\n'
    assert cursor_field_path(text, 1) == ['header']  # A comment stays in the header's context.


def test_field_type_at():
    assert field_type_at(POSE_STAMPED, ['header']) == 'std_msgs/Header'
    assert field_type_at(POSE_STAMPED, ['pose', 'position', 'x']) == 'double'
    assert field_type_at(POSE_STAMPED, ['nope']) is None


def test_matched_wizard_finds_header():
    match = matched_wizard(POSE_STAMPED, ['header'])
    assert match is not None
    path, cls = match
    assert path == ['header']
    assert cls is HeaderWizardPopup


def test_matched_wizard_none_for_plain_field():
    assert matched_wizard(POSE_STAMPED, ['pose', 'position', 'x']) is None


def test_matched_wizard_falls_back_outward_for_plain_leaf():
    # Cursor sits on header.frame_id (a plain string, no wizard) → fall back to the header.
    match = matched_wizard(POSE_STAMPED, ['header', 'frame_id'])
    assert match is not None
    assert match[0] == ['header']
    assert match[1] is HeaderWizardPopup


def test_matched_wizard_returns_innermost_time():
    # Cursor on the header.stamp row opens the Time wizard, not the enclosing Header wizard.
    match = matched_wizard(POSE_STAMPED, ['header', 'stamp'])
    assert match == (['header', 'stamp'], TimeWizardPopup)


def test_matched_wizard_innermost_from_stamp_leaf():
    # Even on a stamp sub-field (sec/nanosec have no wizard) it resolves outward to Time.
    match = matched_wizard(POSE_STAMPED, ['header', 'stamp', 'sec'])
    assert match == (['header', 'stamp'], TimeWizardPopup)


def test_matched_wizard_header_line_still_opens_header():
    match = matched_wizard(POSE_STAMPED, ['header'])
    assert match == (['header'], HeaderWizardPopup)


# A DiagnosticStatus-shaped structure: an integer `level` field carrying enum constants.
DIAGNOSTIC = (
    FieldNode('level', 'octet', (), (('OK', 0), ('WARN', 1), ('ERROR', 2), ('STALE', 3))),
    FieldNode('name', 'string'),
)


def test_matched_wizard_enum_field_binds_choices_into_factory():
    match = matched_wizard(DIAGNOSTIC, ['level'])
    assert match is not None
    prefix, factory = match
    assert prefix == ['level']
    assert factory.func is EnumWizardPopup
    assert factory.keywords['choices'] == (('OK', 0), ('WARN', 1), ('ERROR', 2), ('STALE', 3))


def test_matched_wizard_none_for_plain_string_field():
    assert matched_wizard(DIAGNOSTIC, ['name']) is None


def test_field_block_range_scalar_header():
    assert field_block_range(SEED, ['header']) == (0, 1, 0)


def test_field_block_range_nested_block():
    lines = SEED.splitlines()
    start = lines.index('pose:')
    result = field_block_range(SEED, ['pose'])
    assert result == (start, len(lines), 0)


def test_field_block_range_stops_before_comment():
    text = 'header: auto\npose:\n  position:\n    x: 0.0\n# constants: FOO=1\n'
    lines = text.splitlines()
    assert field_block_range(text, ['pose']) == (lines.index('pose:'), lines.index('# constants: FOO=1'), 0)


def test_render_field_block_scalar():
    assert render_field_block('header', 'auto', 0).strip() == 'header: auto'


def test_render_field_block_nested_indented():
    value = {'stamp': {'sec': 1, 'nanosec': 2}, 'frame_id': 'map'}
    rendered = render_field_block('header', value, 0)
    assert rendered.splitlines()[0] == 'header:'
    assert '  stamp:' in rendered
    assert '    sec: 1' in rendered
    assert '  frame_id: map' in rendered


def test_render_field_block_applies_indent():
    rendered = render_field_block('header', {'frame_id': 'map'}, 2)
    assert rendered.splitlines()[0] == '  header:'
    assert '    frame_id: map' in rendered


def test_replace_block_swaps_lines_and_reports_row():
    new_block = 'header:\n  stamp: now\n  frame_id: map'
    new_text, cursor_row = replace_block(SEED, 0, 1, new_block)
    assert cursor_row == 0
    assert new_text.startswith('header:\n  stamp: now\n  frame_id: map\npose:')
    assert new_text.endswith('\n')  # Preserves the trailing newline.


# --------------------------------------------------------------------------- quaternion wizard


def test_matched_wizard_finds_quaternion():
    match = matched_wizard(POSE_STAMPED, ['pose', 'orientation'])
    assert match is not None
    path, cls = match
    assert path == ['pose', 'orientation']
    assert cls is QuaternionWizardPopup


def test_normalize_quat_scales_to_unit():
    x, y, z, w = normalize_quat(1.0, 1.0, 1.0, 1.0)
    assert (x, y, z, w) == (0.5, 0.5, 0.5, 0.5)


def test_normalize_quat_zero_is_identity():
    assert normalize_quat(0.0, 0.0, 0.0, 0.0) == (0.0, 0.0, 0.0, 1.0)


def test_clean_quat_rounds_and_collapses_negative_zero():
    cleaned = clean_quat(1e-9, -0.0, 0.50000049, 0.99999999)
    assert cleaned == {'x': 0.0, 'y': 0.0, 'z': 0.5, 'w': 1.0}
    assert math.copysign(1.0, cleaned['y']) == 1.0  # -0.0 collapsed to +0.0


def test_quat_about_axis_zero_axis_is_identity():
    # Zero axis short-circuits before importing tf, so this runs without a ROS environment.
    assert quat_about_axis(0.0, 0.0, 0.0, 1.5) == (0.0, 0.0, 0.0, 1.0)


@requires_tf
def test_quat_from_euler_yaw_90():
    x, y, z, w = quat_from_euler(0.0, 0.0, math.pi / 2)
    assert (x, y) == pytest.approx((0.0, 0.0), abs=1e-9)
    assert (z, w) == pytest.approx((_SQRT_HALF, _SQRT_HALF), abs=1e-9)


@requires_tf
def test_quat_about_axis_z_matches_yaw():
    assert quat_about_axis(0.0, 0.0, 1.0, math.pi / 2) == pytest.approx(
        quat_from_euler(0.0, 0.0, math.pi / 2), abs=1e-9
    )


@requires_tf
def test_quat_from_euler_known_triple():
    # Reference values from transforms3d (what tf_transformations wraps), sxyz order, xyzw out.
    assert quat_from_euler(0.5, 0.2, -0.3) == pytest.approx(
        (0.25786, 0.05886, -0.16849, 0.94956), abs=1e-5
    )


# --------------------------------------------------------------------------- time wizard helpers


def test_seconds_str_to_stamp_decimal():
    assert seconds_str_to_stamp('2.5') == {'sec': 2, 'nanosec': 500000000}


def test_seconds_str_to_stamp_integer_and_fraction_only():
    assert seconds_str_to_stamp('7') == {'sec': 7, 'nanosec': 0}
    assert seconds_str_to_stamp('.25') == {'sec': 0, 'nanosec': 250000000}


def test_seconds_str_to_stamp_truncates_beyond_nanoseconds():
    # More than 9 fractional digits: extra precision is dropped, not rounded.
    assert seconds_str_to_stamp('1.0000000009') == {'sec': 1, 'nanosec': 0}


def test_seconds_str_to_stamp_rejects_negative_and_junk():
    with pytest.raises(ValueError):
        seconds_str_to_stamp('-1')
    with pytest.raises(ValueError):
        seconds_str_to_stamp('abc')


def test_epoch_to_stamp_fractional_and_carry():
    assert epoch_to_stamp(10.25) == {'sec': 10, 'nanosec': 250000000}
    assert epoch_to_stamp(5.0) == {'sec': 5, 'nanosec': 0}
    assert epoch_to_stamp(-3.0) == {'sec': 0, 'nanosec': 0}  # clamped at zero


def test_parse_wallclock_round_trips_through_epoch_to_stamp():
    # Deterministic: a fixed local wall-clock string maps back to whole seconds (no fraction).
    stamp = epoch_to_stamp(parse_wallclock('2026-01-02 03:04:05'))
    assert stamp['nanosec'] == 0
    assert stamp['sec'] > 0


def test_stamp_to_seconds_str_trims():
    assert stamp_to_seconds_str({'sec': 2, 'nanosec': 500000000}) == '2.5'
    assert stamp_to_seconds_str({'sec': 7, 'nanosec': 0}) == '7'
    assert stamp_to_seconds_str({'sec': 2, 'nanosec': 7}) == '2.000000007'


def test_parse_time_prefill():
    assert _parse_time('now') == ('now', '0.0')
    assert _parse_time({'sec': 2, 'nanosec': 500000000}) == ('seconds', '2.5')
    assert _parse_time(None) == ('now', '0.0')


def test_parse_header_returns_stamp_dict_for_manual():
    assert _parse_header({'stamp': {'sec': 5, 'nanosec': 7}, 'frame_id': 'map'}) == (
        'manual',
        'map',
        {'sec': 5, 'nanosec': 7},
    )
    assert _parse_header({'stamp': 'now', 'frame_id': 'odom'}) == ('now', 'odom', None)
    assert _parse_header('auto') == ('auto', '', None)
