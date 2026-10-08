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

"""The field helpers, over the live demo world: Quaternion, Header and Enum.

/goal_pose (Publish): the [f Header] and [f Quaternion] badges, f on pose.orientation, tab tab to
"yaw only (°)", 90, enter writes {x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}; u undoes it, esc in a
helper changes nothing, and the Header helper's modes. /diagnostic_status (Publish): f on level
lists OK / WARN / ERROR / STALE, j enter picks WARN; i, "err", esc makes it 2 (ERROR); f on a
plain string field says it has no helper.
"""

import pytest
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]

YAW_90 = '{x: 0.0, y: 0.0, z: 0.707107, w: 0.707107}'
IDENTITY = '{x: 0.0, y: 0.0, z: 0.0, w: 1.0}'


async def test_quaternion_and_header_helpers():
    async with ui_session() as s:
        await s.keys('slash', *'goal', 'enter', 'enter')
        assert s.state()['path'] == ['tabs', '/goal_pose', 'message']
        assert s.line_with('header: auto', '[f Header]', '# Header')
        assert s.line_with('MESSAGE', 'f opens the Header helper') and 'f Header helper' in s.footer()
        assert s.line_with('▾ pose') and s.line_with('position: {x: 0.0')  # pose starts unfolded.
        await s.keys('j', 'j', 'j')  # Down to pose.orientation.
        assert s.state()['row'] == 3
        assert s.line_with('orientation: ' + IDENTITY, '[f Quaternion]', '# Quaternion')
        assert s.line_with('header: auto', '[f Header]') and not s.line_with('position', '[f')
        assert s.line_with('MESSAGE', 'f opens the Quaternion helper') and 'f Quaternion helper' in s.footer()
        await s.shot('badges', expect='inside MESSAGE of /goal_pose, pose unfolded from the start: "header: auto" ends in a '
                     '"[f Header]" badge and "orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}" (the cursor row) in a '
                     'brighter "[f Quaternion]" badge; position has none; the title says "f opens the Quaternion '
                     'helper"; the footer ends "f Quaternion helper  ? keys"')

        await s.keys('f')
        assert s.state()['mode'] == 'helper' and (s.state()['esc'], s.state()['enter']) == ('cancel', 'apply')
        assert s.line_with('pose.orientation', 'Quaternion · Quaternion helper')
        assert s.line_with('x y z w', 'roll pitch yaw (°)', 'yaw only (°)', 'axis + angle (°)')
        assert s.line_with('= ' + IDENTITY)
        await s.keys('tab', 'tab', '9', '0')
        assert s.line_with('yaw', '90') and s.line_with('= ' + YAW_90)
        assert s.line_with('tab next way to enter it · ↑↓ field · type to change · enter applies · esc cancels')
        await s.shot('goal-pose-quat-helper', expect='the Quaternion helper popup right under the orientation row: '
                     'title "pose.orientation  Quaternion · Quaternion helper", the mode strip with "yaw only (°)" lit, '
                     'the field "yaw" holding 90 (lit, with the text cursor), the green preview "= {x: 0.0, y: 0.0, '
                     'z: 0.707107, w: 0.707107}" and the key hint line; the footer badge is HELPER (yellow), '
                     '"esc cancel  enter apply"')

        await s.keys('enter')
        assert s.state()['mode'] == 'normal' and s.state()['layer'] == 'area'
        assert s.line_with('orientation: ' + YAW_90, '[f Quaternion]')
        await s.shot('quat-applied', expect=f'the popup is gone and the orientation row reads "{YAW_90}"; the mode '
                     'badge is NORMAL again and the cursor is still on orientation')

        await s.keys('u')
        assert s.line_with('orientation: ' + IDENTITY)

        await s.keys('f', 'tab', '4', '5', 'escape')
        assert s.line_with('orientation: ' + IDENTITY) and s.state()['mode'] == 'normal'
        await s.shot('helper-esc', expect=f'u undid the helper and esc closed a second one: orientation reads '
                     f'"{IDENTITY}" again, no popup, NORMAL')

        await s.keys('g', 'g', 'f')
        assert s.line_with('header', 'Header · Header helper')
        assert s.line_with('auto', 'now', 'manual') and s.line_with('empty header, stamped at send')
        assert s.line_with('nothing to fill in') and s.line_with('= auto — stamped when sent')
        await s.keys('tab')
        assert s.line_with('stamped at send, with a frame') and s.line_with('frame_id', 'map')
        assert s.line_with('= stamp: now · frame_id: map')
        await s.shot('header-helper', expect='the Header helper under the header row: modes auto / now / manual with '
                     '"now" lit, "stamped at send, with a frame", the field "frame_id" holding map, the preview "= '
                     'stamp: now · frame_id: map"')
        await s.keys('tab', 'down', *'2.5')
        assert s.line_with('= stamp: 2 s 500000000 ns · frame_id: map')
        await s.keys('backspace', 'backspace', 'backspace', '-')
        assert s.line_with('= fix the values first')
        await s.shot('header-bad', expect='the Header helper in "manual" with the stamp "-": the preview is red, '
                     '"= fix the values first"')
        await s.keys('enter')
        assert s.state()['mode'] == 'helper' and s.state()['toast'] == ['fix the highlighted values first', 'bad']
        await s.keys('shift+tab', 'enter')
        assert s.line_with('header: {stamp: now, frame_id: map}', '[f Header]')


async def test_enum_helper():
    async with ui_session() as s:
        await s.keys('slash', *'diag', 'enter', 'e')
        assert s.state()['path'] == ['tabs', '/diagnostic_status'] and s.line_with('level: 0 OK', '[f Enum]')
        await s.keys('f')
        assert s.state()['mode'] == 'helper' and s.state()['path'] == ['tabs', '/diagnostic_status', 'message']
        assert s.line_with('level', 'octet · Enum helper')
        for index, name in enumerate(('OK', 'WARN', 'ERROR', 'STALE')):
            assert s.line_with(f'{index} {name} = {index}')
        assert s.line_with('● 0 OK') and s.line_with('= 0  (OK)')
        assert s.line_with('j k or ↑↓ pick · 0–3 jump · enter applies · esc cancels')
        await s.keys('j')
        assert s.line_with('● 1 WARN') and s.line_with('= 1  (WARN)')
        await s.shot('enum-helper', expect='f on level of /diagnostic_status (Publish) went into MESSAGE and opened the '
                     'Enum helper: "level  octet · Enum helper", the options ○ 0 OK = 0, ● 1 WARN = 1 (on a band), '
                     '○ 2 ERROR = 2, ○ 3 STALE = 3, the preview "= 1  (WARN)" and the key hint line')
        await s.keys('enter')
        assert s.line_with('level: 1 WARN', '[f Enum]')

        await s.keys('i', 'backspace', *'err')
        assert s.line_with('level: err', 'ERROR=2 · type a name or number')
        await s.shot('enum-typing', expect='i on level and "err" typed: the edit box, then the completion "ERROR=2 · '
                     'type a name or number" in grey-blue instead of the type hint')
        await s.keys('escape')
        assert s.line_with('level: 2 ERROR')
        await s.shot('enum-typed', expect='esc kept it: level reads "2 ERROR" (ERROR dim) with its [f Enum] badge')

        await s.keys('c', *'hot', 'enter')
        assert s.state()['layer'] == 'edit'
        assert s.line_with('✗ level needs OK / WARN / ERROR / STALE or a number, got "hot"')
        await s.keys('escape')
        assert s.line_with('level: 2 ERROR')

        await s.advance(2.0)
        await s.keys('j', 'f')
        assert s.state()['toast'] == ['no helper for this field — fields with one show [f …]', 'bad']
        assert s.state()['mode'] == 'normal'
        await s.shot('no-helper', expect='f on the name row (a plain string): no popup, the red toast "no helper for '
                     'this field — fields with one show [f …]" bottom right')
