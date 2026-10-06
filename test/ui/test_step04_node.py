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

"""Step 4: the panels (areas) and the node entry over the live demo world.

/ros_tui_demo_servers: picking an area (selected) vs. being inside it, editing a parameter in
insert mode, a bad value with its errline, a kept change ("5.0 was 10.0"), setting it with space,
per-tab undo, and opening an interface in a tab. Design references: node-open, node-params-editing,
node-param-error, node-param-changed (docs/design/reference_shots.json).
"""

import pytest
from harness.fake_bridge import SERVICE_DELAY_S
from harness.screens import ui_session
from ros_tui.constants import NAV_TOAST_S
from ros_tui.ui.next_app import NextApp

pytestmark = [pytest.mark.ui, pytest.mark.shots]

NODE = '/ros_tui_demo_servers'


def footer(s) -> str:
    return s.text().splitlines()[-1]


def line_with(s, *parts) -> str:
    """The first screen line holding all of `parts` ('' if none)."""
    return next((line for line in s.text().splitlines() if all(part in line for part in parts)), '')


def where(s) -> tuple:
    state = s.state()
    return state['layer'], state['mode'], state['path'], state['area'], state['row']


async def test_node_entry():
    async with ui_session(app_factory=NextApp) as s:
        await s.keys('G', 'k', 'enter')  # The last two rows of the ☰ list are the nodes.
        assert s.state()['tabs'] == [NODE]
        assert s.text().count('loading…') == 2
        await s.shot('node-loading', expect=f'{NODE} just opened: INTERFACES and PARAMETERS both say "loading…"')

        await s.advance(SERVICE_DELAY_S * 2)
        assert where(s) == ('in', 'normal', ['tabs', NODE], 'ifs', 0)
        text = s.text()
        for expected in ('◆ NODE', 'namespace /', 'INTERFACES  enter opens it in a tab', '▾ Publishes',
                         '≋ /chatter', '▾ Subscribes', '≋ /goal_pose', '▾ Serves', '⇄ /add_two_ints', '⇄ /set_pose',
                         '▾ Action server', '▷ /fibonacci', 'PARAMETERS  enter edits · space sets'):
            assert expected in text, expected
        assert 'Calls' not in text and 'Action client' not in text  # Empty groups aren't listed.
        assert line_with(s, 'use_sim_time', 'bool', 'false') and line_with(s, 'publish_rate', 'double', '10.0')
        assert line_with(s, 'frame_id', 'string', 'map')
        assert 'esc tab row' in footer(s) and 'enter into interfaces' in footer(s)
        await s.shot('node-open', expect='◆ NODE /ros_tui_demo_servers namespace /; INTERFACES (selected: white '
                     'border, title on a lighter band) lists ▾ Publishes /chatter /counter /diagnostic_status '
                     '/localisation_pose, ▾ Subscribes /inbox /goal_pose, ▾ Serves /add_two_ints /set_pose, ▾ Action '
                     'server /fibonacci with their kind glyphs; PARAMETERS at rest: use_sim_time bool false, '
                     'publish_rate double 10.0, frame_id string map; footer NORMAL tabs › /ros_tui_demo_servers, '
                     'esc tab row, enter into interfaces')

        await s.keys('l')
        assert where(s) == ('in', 'normal', ['tabs', NODE], 'par', 0)
        assert 'enter into parameters' in footer(s)
        await s.shot('node-params-selected', expect='PARAMETERS is selected (white border), INTERFACES back at rest; '
                     'no row is highlighted yet; footer enter into parameters')

        await s.keys('enter', 'j')
        assert where(s) == ('area', 'normal', ['tabs', NODE, 'parameters'], 'par', 1)
        assert 'esc pick another area' in footer(s) and 'enter edit' in footer(s)
        await s.shot('node-params-inside', expect='inside PARAMETERS: a blue border, the publish_rate row on a '
                     'blue-grey band with a blue ▍ bar; footer NORMAL tabs › … › parameters, esc pick another area, '
                     'enter edit')

        await s.keys('enter')
        assert where(s) == ('edit', 'insert', ['tabs', NODE, 'parameters', 'editing'], 'par', 1)
        assert ' INSERT ' in footer(s) and 'esc keep it' in footer(s) and 'enter keep it' in footer(s)
        await s.shot('node-params-editing', expect='publish_rate in insert: its value 10.0 on the edit background '
                     'with a text cursor after it; footer INSERT (green) tabs › … › parameters › editing')

        await s.keys('backspace', 'backspace', 'backspace', 'backspace', '5', 'x', 'enter')
        assert s.state()['layer'] == 'edit'
        assert line_with(s, '│ ✗ publish_rate needs a number, got "5x"')
        assert line_with(s, 'publish_rate', '5x')
        await s.shot('node-param-error', expect='still in insert (INSERT badge) with publish_rate 5x; a red errline '
                     '"✗ publish_rate needs a number, got "5x"" at the bottom of PARAMETERS; the activity strip has '
                     'the same ✗ line in red')

        await s.keys('backspace', 'escape')
        assert where(s) == ('area', 'normal', ['tabs', NODE, 'parameters'], 'par', 1)
        assert not line_with(s, '│ ✗ publish_rate needs a number')
        assert line_with(s, 'publish_rate', 'double', '5.0 was 10.0')
        assert 'PARAMETERS  ● changed · space sets' in s.text()
        assert s.bridge.set_param_calls == []
        await s.shot('node-param-changed', expect='publish_rate shows 5.0 in yellow and "was 10.0" dim; the title '
                     'reads "● changed · space sets" in yellow; the errline is gone; nothing was sent')

        await s.keys('space')
        await s.advance(SERVICE_DELAY_S * 2)
        assert s.bridge.set_param_calls == [(NODE, 'publish_rate', '5.0')]
        assert line_with(s, NODE, '✓ set publish_rate = 5.0')
        assert line_with(s, 'publish_rate', 'double', '5.0') and 'was 10.0' not in s.text()
        assert 'PARAMETERS  enter edits · space sets' in s.text()
        await s.shot('node-param-set', expect='space set it: the activity strip shows "◆ /ros_tui_demo_servers ✓ set '
                     'publish_rate = 5.0" in green; publish_rate is 5.0 without a marker and the title is back to '
                     '"enter edits · space sets"')

        # A new change, then u in another tab leaves it, and u back here undoes it.
        await s.keys('c', '7', 'enter')
        assert line_with(s, 'publish_rate', '7.0 was 5.0')
        await s.keys('0', 'g', 'g', 'enter')  # /chatter in tab 2.
        assert s.state()['tabs'] == [NODE, '/chatter'] and s.state()['active'] == 1
        await s.keys('u')
        assert s.state()['toast'] == ['nothing to undo in this tab', 'info']
        assert s.app.nav.log[0] == ('u', 'nothing to undo in this tab (2 changes in other tabs are kept)')
        await s.shot('undo-elsewhere', expect='on /chatter, u only toasts "nothing to undo in this tab"')
        await s.keys('1')
        assert line_with(s, 'publish_rate', '7.0 was 5.0')
        await s.keys('u')
        assert line_with(s, 'publish_rate', 'double', '5.0') and 'was 5.0' not in s.text()
        assert s.app.nav.log[0] == ('u', f'undid the change to publish_rate on {NODE}')
        await s.shot('node-param-undone', expect='back on the node, u undid the change: publish_rate is 5.0 again, '
                     'the title reads "enter edits · space sets"')

        # INTERFACES: enter opens an interface in a tab.
        await s.keys('h', 'enter')
        assert where(s) == ('area', 'normal', ['tabs', NODE, 'interfaces'], 'ifs', 0)
        assert 'enter open it' in footer(s)
        await s.keys(*['j'] * 6)
        assert s.state()['row'] == 6
        await s.shot('node-interfaces-inside', expect='inside INTERFACES (blue border), the /add_two_ints row '
                     'highlighted; footer tabs › … › interfaces, enter open it')
        await s.keys('enter')
        state = s.state()
        assert state['tabs'] == [NODE, '/chatter', '/add_two_ints'] and state['active'] == 2
        assert (state['layer'], state['path']) == ('in', ['tabs', '/add_two_ints'])
        assert '⇄ SERVICE' in s.text()
        await s.shot('interface-opened', expect='/add_two_ints opened as tab 3 (⇄ SERVICE header, REQUEST selected)')


async def test_failed_set_stays_changed():
    async with ui_session(app_factory=NextApp) as s:
        s.bridge.rejected_params['frame_id'] = 'frame_id is read-only'
        await s.keys('G', 'k', 'enter')
        await s.advance(SERVICE_DELAY_S * 2)
        await s.keys('space')
        assert s.state()['toast'] == ['change a value first (enter edits it)', 'bad']
        await s.advance(NAV_TOAST_S)
        await s.keys('l', 'enter', 'G', 'c', *'odom', 'enter', 'space')
        await s.advance(SERVICE_DELAY_S * 2)
        assert line_with(s, NODE, '✗ set frame_id: frame_id is read-only')
        assert line_with(s, 'frame_id', 'string', 'odom was map') and '● changed' in s.text()
        await s.shot('node-param-rejected', expect='the node rejected frame_id: a red "✗ set frame_id: frame_id is '
                     'read-only" activity line, and frame_id still shows odom (yellow) was map with "● changed"')
