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

"""The field-row editor and the service entry over the live demo world.

/add_two_ints: editing the request (insert, tab to the next field), calling it ("calling…", then
"✓ OK" with sum: 42 and the time on the bridge's clock), a bad value with its errline, and [ ] through
the earlier requests back to the draft. /set_pose (TeleportAbsolute) answers with an empty response,
a failing service shows "✗ FAILED", and /camera/set_camera_info (not in the demo world) shows nested
messages and lists folding in place. Design references: service-open, service-editing,
service-called, service-error, service-history (docs/design/reference_shots.json).
"""

import pytest
from harness.fake_bridge import SERVICE_DELAY_S, FakeBridge, camera_demo
from harness.screens import ui_session

pytestmark = [pytest.mark.ui, pytest.mark.shots]

ADD = '/add_two_ints'


def footer(s) -> str:
    return s.text().splitlines()[-1]


def line_with(s, *parts) -> str:
    """The first screen line holding all of `parts` ('' if none)."""
    return next((line for line in s.text().splitlines() if all(part in line for part in parts)), '')


def where(s) -> tuple:
    state = s.state()
    return state['layer'], state['mode'], state['path'], state['area'], state['row']


async def test_service_entry():
    async with ui_session() as s:
        await s.keys('slash', *'add', 'enter')
        assert where(s) == ('in', 'normal', ['tabs', ADD], 'msg', 0)
        for expected in ('⇄ SERVICE', 'example_interfaces/srv/AddTwoInts', '▶ Call space', '[ ] earlier requests',
                         'REQUEST  i edit · p paste', 'RESPONSE  not called yet'):
            assert expected in s.text(), expected
        assert line_with(s, '1  a: 0', '# int64') and line_with(s, '2  b: 0', '# int64')
        assert 'enter into request' in footer(s)
        await s.shot('service-open', expect='⇄ SERVICE /add_two_ints example_interfaces/srv/AddTwoInts; a blue '
                     '"▶ Call space" button, "[ ] earlier requests" on the right; REQUEST (selected, white border) with '
                     'rows "1  a: 0  # int64" and "2  b: 0  # int64", numbers in green; RESPONSE "not called yet"')

        await s.keys('enter', 'enter', '1', '9')
        assert where(s) == ('edit', 'insert', ['tabs', ADD, 'request', 'editing'], 'msg', 0)
        assert line_with(s, 'a: 19')
        await s.shot('service-editing', expect='inside REQUEST (blue border), a in insert: 19 in the underlined '
                     'edit box with the text cursor; footer INSERT tabs › /add_two_ints › request › editing')

        await s.keys('tab', '2', '3', 'escape')
        assert where(s) == ('area', 'normal', ['tabs', ADD, 'request'], 'msg', 1)
        assert line_with(s, 'a: 19') and line_with(s, 'b: 23')
        assert s.bridge.service_calls == []

        await s.keys('space')
        assert 'calling…' in line_with(s, 'RESPONSE') and line_with(s, ADD, '▶ called · a: 19, b: 23')
        await s.shot('service-calling', expect='space called it: the RESPONSE title has a cyan "calling…" pill and '
                     'says "waiting for the response…"; ACTIVITY "⇄ /add_two_ints ▶ called · a: 19, b: 23"')

        await s.advance(SERVICE_DELAY_S * 2)
        assert line_with(s, 'RESPONSE', '✓ OK', '50.0 ms') and line_with(s, '1  sum: 42', '# int64')
        assert line_with(s, ADD, '✓ response · sum: 42 (50.0 ms)')
        assert 'REQUEST  [ ] history (1) · i edit · p paste' in s.text()
        await s.shot('service-called', expect='RESPONSE "✓ OK" (green pill) 50.0 ms with "1  sum: 42  # int64"; the '
                     'REQUEST title now starts "[ ] history (1)"; ACTIVITY has "▶ called · a: 19, b: 23" and '
                     '"✓ response · sum: 42 (50.0 ms)" in green')

        await s.keys('k', 'c', *'abc', 'enter')
        assert s.state()['layer'] == 'edit'
        assert line_with(s, '│ ✗ a needs a whole number, got "abc"')
        assert line_with(s, ADD, '✗ a needs a whole number, got "abc"')
        await s.shot('service-error', expect='still in insert with a = abc; a red errline "✗ a needs a whole number, '
                     'got "abc"" at the bottom of REQUEST and the same line in red in ACTIVITY')

        await s.keys('backspace', 'backspace', 'backspace', '5', 'enter', 'space')
        await s.advance(SERVICE_DELAY_S * 2)
        assert not line_with(s, '│ ✗')
        assert line_with(s, '1  sum: 28') and line_with(s, ADD, '✓ response · sum: 28 (50.0 ms)')

        await s.keys('enter', 'backspace', '7', 'escape', 'left_square_bracket')
        assert line_with(s, 'a: 5') and 'REQUEST  [ ] history #1/2' in s.text()
        assert s.app.nav.log[0] == ('[', 'loaded send 1 of 2 (1 = newest) · ] goes newer')
        await s.keys('left_square_bracket')
        assert line_with(s, 'a: 19') and 'history #2/2' in s.text()
        await s.shot('service-history', expect='[ [ loaded the oldest request: a 19, b 23; the REQUEST title says '
                     '"[ ] history #2/2"')
        await s.keys('right_square_bracket', 'right_square_bracket')
        assert line_with(s, 'a: 7') and 'REQUEST  [ ] history (2)' in s.text()
        assert s.app.nav.log[0] == (']', 'back to your own edit')
        await s.shot('service-draft', expect='] ] went back past the newest send to the draft: a 7, b 23; the title '
                     'says "[ ] history (2)" again')

        await s.keys('u')
        assert line_with(s, 'a: 5')

        await s.keys('slash', *'set_pose', 'enter', 'enter', 'enter', '5', 'escape', 'space')
        await s.advance(SERVICE_DELAY_S * 2)
        assert s.state()['tabs'] == [ADD, '/set_pose']
        assert line_with(s, 'x: 5.0', '# float') and line_with(s, 'theta: 0.0')
        assert line_with(s, 'RESPONSE', '✓ OK') and 'empty response (no fields)' in s.text()
        assert line_with(s, '/set_pose', '▶ called · x: 5.0, y: 0.0, theta: 0.0')
        await s.shot('set-pose-called', expect='/set_pose (turtlesim/srv/TeleportAbsolute) called with x 5.0: RESPONSE '
                     '"✓ OK 50.0 ms" and "empty response (no fields)"; ACTIVITY shows the /set_pose call and '
                     'response, the /add_two_ints lines dimmed')

        await s.keys('1')
        assert line_with(s, 'a: 5') and line_with(s, '1  sum: 28')  # Each entry keeps its own state.


async def test_failed_call():
    bridge = FakeBridge.demo()
    bridge.failing_services[ADD] = f'service {ADD} not available'
    async with ui_session(bridge=bridge) as s:
        await s.keys('slash', *'add', 'enter', 'space')
        await s.advance(SERVICE_DELAY_S * 2)
        assert line_with(s, 'RESPONSE', '✗ FAILED', '50.0 ms')
        assert line_with(s, f'│ ✗ call failed: service {ADD} not available')
        assert line_with(s, ADD, f'✗ call failed: service {ADD} not available (50.0 ms)')
        await s.shot('service-failed', expect='RESPONSE has a red "✗ FAILED" pill, 50.0 ms, and the red errline '
                     '"✗ call failed: service /add_two_ints not available"; the same in red in ACTIVITY')


async def test_nested_request():
    async with ui_session(bridge=camera_demo()) as s:
        await s.keys('slash', *'camera', 'enter')
        for expected in ('▾ camera_info', 'header: auto', 'height: 0', "distortion_model: ''", '▸ d [0 items]',
                         '▸ k [9 items]', '▸ roi {…}'):
            assert line_with(s, expected), expected
        await s.shot('nested-open', expect='/camera/set_camera_info: REQUEST has "▾ camera_info" unfolded, its '
                     'fields one level in: header: auto (one row), height, width, distortion_model, ▸ d [0 items] '
                     '# double[], ▸ k [9 items] # double[9], … ▸ roi {…} # RegionOfInterest')

        await s.keys('enter', 'G')
        assert 'enter unfold' in footer(s)
        await s.keys('enter')
        assert line_with(s, '▾ roi') and line_with(s, 'do_rectify: false', '# boolean')
        await s.keys('j', 'j', 'h')
        assert where(s)[4] == 11 and 'enter fold' in footer(s)
        await s.shot('nested-unfolded', expect='enter unfolded roi: x_offset, y_offset, height, width, do_rectify '
                     'indented under "▾ roi"; j j h went back up to the roi row; footer "enter fold"')

        await s.keys('g', 'g', *['j'] * 5, 'o', *'0.5', 'enter', 'o', *'-0.1', 'enter')
        assert line_with(s, '▾ d [2 items]') and line_with(s, '[0]: 0.5') and line_with(s, '[1]: -0.1')
        await s.keys('k', 'd')
        assert line_with(s, '▾ d [1 item]') and line_with(s, '[0]: -0.1')
        await s.shot('nested-list', expect='o added d[0] = 0.5 and d[1] = -0.1, then d on [0] deleted it: '
                     '"▾ d [1 item]" with "[0]: -0.1" under it')

        await s.keys('space')
        await s.advance(SERVICE_DELAY_S * 2)
        assert line_with(s, 'success: true') and line_with(s, "status_message: 'stored'")
        assert s.bridge.service_calls[0][2].camera_info.d.tolist() == [-0.1]
