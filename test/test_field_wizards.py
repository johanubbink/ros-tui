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
    HeaderWizardPopup,
    QuaternionWizardPopup,
    clean_quat,
    cursor_field_path,
    field_block_range,
    field_type_at,
    matched_wizard,
    normalize_quat,
    quat_about_axis,
    quat_from_euler,
    render_field_block,
    replace_block,
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

# A PoseStamped-shaped structure: header (std_msgs/Header) + pose.{position,orientation}.
POSE_STAMPED = (
    FieldNode('header', 'std_msgs/Header', (FieldNode('frame_id', 'string'),)),
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


def test_matched_wizard_returns_outermost():
    # Cursor sits on header.frame_id; the header (outer) has the wizard, not frame_id.
    match = matched_wizard(POSE_STAMPED, ['header', 'frame_id'])
    assert match is not None
    assert match[0] == ['header']


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
