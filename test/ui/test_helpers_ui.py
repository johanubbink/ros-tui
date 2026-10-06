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

"""The field helpers, over the live demo world, following the design's try-steps 7 and 8.

/goal_pose (Publish): the [f Header] and [f Quaternion] badges, f on pose.orientation, tab tab to
"yaw only (°)", 90, enter writes {x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}; u undoes it, esc in a
helper changes nothing, and the Header helper's modes. /diagnostic_status (Publish): f on level
lists OK / WARN / ERROR / STALE, j enter picks WARN; i, "err", esc makes it 2 (ERROR); f on a
plain string field says it has no helper. Design references: goal-pose-quat-helper, header-helper,
enum-helper, enum-typed (docs/design/reference_shots.json).
"""

import pytest
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]

YAW_90 = '{x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}'
IDENTITY = '{x: 0.0, y: 0.0, z: 0.0, w: 1.0}'


def footer(s) -> str:
    return s.text().splitlines()[-1]


def line_with(s, *parts) -> str:
    """The first screen line holding all of `parts` ('' if none)."""
    return next((line for line in s.text().splitlines() if all(part in line for part in parts)), '')


async def test_quaternion_and_header_helpers():
    async with ui_session() as s:
        await s.keys('slash', *'goal', 'enter', 'enter')
        assert s.state()['path'] == ['tabs', '/goal_pose', 'message']
        assert line_with(s, 'header: auto', '[f Header]', '# Header')
        assert line_with(s, 'MESSAGE', 'f opens the Header helper') and 'f Header helper' in footer(s)
        assert line_with(s, '▾ pose') and line_with(s, 'position: {x: 0.0')  # pose starts unfolded.
        await s.keys('j', 'j', 'j')  # Down to pose.orientation.
        assert s.state()['row'] == 3
        assert line_with(s, 'orientation: ' + IDENTITY, '[f Quaternion]', '# Quaternion')
        assert line_with(s, 'header: auto', '[f Header]') and not line_with(s, 'position', '[f')
        assert line_with(s, 'MESSAGE', 'f opens the Quaternion helper') and 'f Quaternion helper' in footer(s)
        await s.shot('badges', expect='inside MESSAGE of /goal_pose, pose unfolded from the start: "header: auto" ends in a '
                     '"[f Header]" badge and "orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}" (the cursor row) in a '
                     'brighter "[f Quaternion]" badge; position has none; the title says "f opens the Quaternion '
                     'helper"; the footer ends "f Quaternion helper  ? keys"')

        await s.keys('f')
        assert s.state()['mode'] == 'helper' and (s.state()['esc'], s.state()['enter']) == ('cancel', 'apply')
        assert line_with(s, 'pose.orientation', 'Quaternion · Quaternion helper')
        assert line_with(s, 'x y z w', 'roll pitch yaw (°)', 'yaw only (°)', 'axis + angle (°)')
        assert line_with(s, '= ' + IDENTITY)
        await s.keys('tab', 'tab', '9', '0')
        assert line_with(s, 'yaw', '90') and line_with(s, '= ' + YAW_90)
        assert line_with(s, 'tab next way to enter it · ↑↓ field · type to change · enter applies · esc cancels')
        await s.shot('goal-pose-quat-helper', expect='the Quaternion helper popup right under the orientation row: '
                     'title "pose.orientation  Quaternion · Quaternion helper", the mode strip with "yaw only (°)" lit, '
                     'the field "yaw" holding 90 (lit, with the text cursor), the green preview "= {x: 0.0, y: 0.0, '
                     'z: 0.707107, w: 0.707107}" and the key hint line; the footer badge is HELPER (yellow), '
                     '"esc cancel  enter apply"')

        await s.keys('enter')
        assert s.state()['mode'] == 'normal' and s.state()['layer'] == 'area'
        assert line_with(s, 'orientation: ' + YAW_90, '[f Quaternion]')
        assert s.app.nav.log[0] == ('enter', f'filled pose.orientation = {YAW_90} (u undoes)')
        await s.shot('quat-applied', expect=f'the popup is gone and the orientation row reads "{YAW_90}"; the mode '
                     'badge is NORMAL again and the cursor is still on orientation')

        await s.keys('u')
        assert line_with(s, 'orientation: ' + IDENTITY)
        assert s.app.nav.log[0] == ('u', 'undid the Quaternion helper on pose.orientation on /goal_pose')

        await s.keys('f', 'tab', '4', '5', 'escape')
        assert line_with(s, 'orientation: ' + IDENTITY) and s.state()['mode'] == 'normal'
        assert s.app.nav.log[0] == ('esc', 'helper closed, nothing changed')
        await s.shot('helper-esc', expect=f'u undid the helper and esc closed a second one: orientation reads '
                     f'"{IDENTITY}" again, no popup, NORMAL')

        await s.keys('g', 'g', 'f')
        assert line_with(s, 'header', 'Header · Header helper')
        assert line_with(s, 'auto', 'now', 'manual') and line_with(s, 'empty header, stamped at send')
        assert line_with(s, 'nothing to fill in') and line_with(s, '= auto — stamped when sent')
        await s.keys('tab')
        assert line_with(s, 'stamped at send, with a frame') and line_with(s, 'frame_id', 'map')
        assert line_with(s, '= stamp: now · frame_id: map')
        await s.shot('header-helper', expect='the Header helper under the header row: modes auto / now / manual with '
                     '"now" lit, "stamped at send, with a frame", the field "frame_id" holding map, the preview "= '
                     'stamp: now · frame_id: map"')
        await s.keys('tab', 'down', *'2.5')
        assert line_with(s, '= stamp: 2 s 500000000 ns · frame_id: map')
        await s.keys('backspace', 'backspace', 'backspace', '-')
        assert line_with(s, '= fix the values first')
        await s.shot('header-bad', expect='the Header helper in "manual" with the stamp "-": the preview is red, '
                     '"= fix the values first"')
        await s.keys('enter')
        assert s.state()['mode'] == 'helper' and s.state()['toast'] == ['fix the highlighted values first', 'bad']
        await s.keys('shift+tab', 'enter')
        assert line_with(s, 'header: {stamp: now, frame_id: map}', '[f Header]')


async def test_enum_helper():
    async with ui_session() as s:
        await s.keys('slash', *'diag', 'enter', 'e')
        assert s.state()['path'] == ['tabs', '/diagnostic_status'] and line_with(s, 'level: 0 OK', '[f Enum]')
        await s.keys('f')
        assert s.state()['mode'] == 'helper' and s.state()['path'] == ['tabs', '/diagnostic_status', 'message']
        assert line_with(s, 'level', 'octet · Enum helper')
        for index, name in enumerate(('OK', 'WARN', 'ERROR', 'STALE')):
            assert line_with(s, f'{index} {name} = {index}')
        assert line_with(s, '● 0 OK') and line_with(s, '= 0  (OK)')
        assert line_with(s, 'j k or ↑↓ pick · 0–3 jump · enter applies · esc cancels')
        await s.keys('j')
        assert line_with(s, '● 1 WARN') and line_with(s, '= 1  (WARN)')
        await s.shot('enum-helper', expect='f on level of /diagnostic_status (Publish) went into MESSAGE and opened the '
                     'Enum helper: "level  octet · Enum helper", the options ○ 0 OK = 0, ● 1 WARN = 1 (on a band), '
                     '○ 2 ERROR = 2, ○ 3 STALE = 3, the preview "= 1  (WARN)" and the key hint line')
        await s.keys('enter')
        assert line_with(s, 'level: 1 WARN', '[f Enum]')
        assert s.app.nav.log[0] == ('enter', 'filled level = 1 (u undoes)')

        await s.keys('i', 'backspace', *'err')
        assert line_with(s, 'level: err', 'ERROR=2 · type a name or number')
        await s.shot('enum-typing', expect='i on level and "err" typed: the edit box, then the completion "ERROR=2 · '
                     'type a name or number" in grey-blue instead of the type hint')
        await s.keys('escape')
        assert line_with(s, 'level: 2 ERROR')
        assert s.app.nav.log[0] == ('esc', 'kept level = 2 (u undoes)')
        await s.shot('enum-typed', expect='esc kept it: level reads "2 ERROR" (ERROR dim) with its [f Enum] badge')

        await s.keys('c', *'hot', 'enter')
        assert s.state()['layer'] == 'edit'
        assert line_with(s, '✗ level needs OK / WARN / ERROR / STALE or a number, got "hot"')
        await s.keys('escape')
        assert line_with(s, 'level: 2 ERROR')

        await s.advance(2.0)
        await s.keys('j', 'f')
        assert s.state()['toast'] == ['no helper for this field — fields with one show [f …]', 'bad']
        assert s.state()['mode'] == 'normal'
        await s.shot('no-helper', expect='f on the name row (a plain string): no popup, the red toast "no helper for '
                     'this field — fields with one show [f …]" bottom right')
