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

"""The overlays over the live demo world.

Search (/ and ^f), the command line (:), the which-key popups (? and g…), toasts and the :log
view. Every overlay closes back to exactly the layer it was opened on.
"""

import pytest
from harness.screens import ui_session
from ros_tui.constants import NAV_TOAST_S
from ros_tui.ui.nav import Tab

pytestmark = [pytest.mark.ui, pytest.mark.shots]


def boxed(s) -> str:
    """What is inside a bordered box on the ☰ list (between the first and the last │ of each line)."""
    return '\n'.join(line[line.index('│') + 1:line.rindex('│')] for line in s.lines() if '│' in line)


PLACE = ('layer', 'mode', 'path', 'active', 'tab_cur', 'chip', 'list_cur', 'area', 'row')  # Where you are.


async def test_search():
    async with ui_session() as s:
        await s.keys('/')
        state = s.state()
        assert (state['mode'], state['search'], state['layer']) == ('search', '', 'in')
        assert 'any topic, service, action or node' in s.text() and s.line_with('/ ', ' 11')
        assert ' SEARCH ' in s.footer() and 'esc' not in s.footer()  # esc / enter labels hide under search.
        await s.shot('search-open', expect='the search box over the dimmed ☰ list: "/ █ any topic, service, action or '
                     'node" and the count 11, all entries grouped ≋ TOPICS … ◆ NODES, the cursor bar on /chatter; '
                     'the hint "↑↓ picks · enter opens in a tab · esc closes"; footer SEARCH tabs › ☰ list')

        await s.type_text('pose')
        text = boxed(s)
        assert s.line_with('/ pose', ' 3')
        for expected in ('/localisation_pose', 'PoseWithCovarianceStamped', '/goal_pose', 'PoseStamped',
                         '/set_pose', 'TeleportAbsolute', 'TOPICS', 'SERVICES'):
            assert expected in text, expected
        assert '/chatter' not in text and 'ACTIONS' not in text
        await s.shot('search-typed', expect='query "pose", 3 matches: ≋ TOPICS /localisation_pose '
                     'PoseWithCovarianceStamped and /goal_pose PoseStamped, ⇄ SERVICES /set_pose TeleportAbsolute; '
                     '"pose" highlighted in each name, the cursor on /localisation_pose')

        await s.keys('down', 'down', 'up', 'ctrl+n')  # ctrl+n is not a search key: swallowed.
        assert s.state()['overlay_cur'] == 1 and '▍' in s.line_with('/goal_pose', 'PoseStamped')
        await s.shot('search-picked', expect='the cursor bar on /goal_pose (down, down, up; ctrl+n does nothing)')

        await s.keys('enter')
        state = s.state()
        assert state['search'] is None and state['tabs'] == ['/goal_pose'] and state['active'] == 0
        assert (state['layer'], state['path']) == ('in', ['tabs', '/goal_pose'])
        assert not s.line_with('/ pose')  # The box is gone.

        await s.keys('enter')  # Inside the MESSAGE area: search keeps exactly this layer.
        before = s.where(*PLACE)
        assert s.where('layer', 'path') == ('area', ['tabs', '/goal_pose', 'message'])
        await s.keys('ctrl+f')
        await s.type_text('go')
        assert s.where('mode', 'path') == ('search', ['tabs', '/goal_pose', 'message'])
        assert 'open tab' in s.line_with('/goal_pose', 'PoseStamped')
        await s.shot('search-open-tab', expect='^f inside /goal_pose\'s MESSAGE area, query "go": /goal_pose is '
                     'marked "open tab"; footer SEARCH tabs › /goal_pose › message')

        await s.keys('escape')
        assert s.state()['search'] is None and s.where(*PLACE) == before
        assert 'esc back out' in s.footer()

        await s.keys('0', '/')
        await s.type_text('zzz')
        assert 'no matches — backspace to change the search' in s.text() and s.line_with('/ zzz', ' 0')
        await s.shot('search-no-match', expect='query "zzz": count 0 and "no matches — backspace to change the '
                     'search"')
        await s.keys('backspace', 'backspace', 'backspace')
        assert s.state()['search'] == '' and s.line_with(' 11')
        await s.keys('escape')
        state = s.state()
        assert (state['search'], state['layer'], state['path']) == (None, 'in', ['tabs', '☰ list'])


async def test_command_line():
    async with ui_session() as s:
        await s.keys(':')
        state = s.state()
        assert (state['mode'], state['cmd']) == ('command', '')
        assert ' COMMAND ' in s.footer() and '↑↓ pick · tab completes · enter runs · esc cancels' in s.footer()
        for name, text in (('log', 'show all activity'), ('services', 'list only services'),
                           ('rate', 'set the repeat rate, e.g. :rate 5')):
            assert text in s.line_with(':' + name), name
        assert ':echo' not in s.text()  # Up to 7 suggestions.
        await s.shot('command-line', expect='the footer is the command line: COMMAND, ":█", the hint on the '
                     'right; above it, bottom left, 7 suggestions :log … :rate with their text, :log highlighted')

        await s.keys('s', 'e')
        assert s.line_with(':services', 'list only services') and 'show all activity' not in s.text()
        await s.keys('tab')
        assert s.state()['cmd'] == 'services' and ':services' in s.footer()
        await s.shot('command-suggest', expect='":se" completed with tab to ":services"; one suggestion left, '
                     ':services list only services, highlighted')
        await s.keys('enter')
        state = s.state()
        assert (state['cmd'], state['chip'], state['mode']) == (None, 1, 'normal')
        assert '0 ☰ Services' in s.text() and '⇄ SERVICES · 2' in s.text() and 'TOPICS ·' not in s.text()

        await s.keys(':', 'down', 'down', 'up')
        assert s.state()['overlay_cur'] == 1
        await s.shot('command-picked', expect='↓ ↓ ↑ picked the second suggestion, :topics, highlighted')
        await s.keys('enter')
        assert (s.state()['cmd'], s.state()['chip']) == (None, 0)

        await s.keys(':', 'x', 'escape')
        state = s.state()
        assert (state['cmd'], state['layer'], state['path']) == (None, 'in', ['tabs', '☰ list'])

        await s.keys(':', 'f', 'o', 'o', 'enter')
        toast = 'unknown command :foo — : then tab lists them'
        assert s.state()['toast'] == [toast, 'bad'] and toast in s.text()
        assert s.state()['cmd'] is None and ' NORMAL ' in s.footer()
        await s.shot('toast-bad', expect=f'a red toast bottom right of the body: "{toast}"; the footer is NORMAL '
                     'again')
        await s.advance(NAV_TOAST_S - 0.4)
        assert toast in s.text()
        await s.advance(0.5)
        assert s.state()['toast'] is None and toast not in s.text()
        await s.shot('toast-gone', expect=f'{NAV_TOAST_S:g} s later (simulated) the toast is gone')

        await s.keys(':', 'h', 'e', 'l', 'p', 'enter')
        assert s.state()['which_key'] == 'all' and 'Keys right now · any key closes' in s.text()
        await s.keys('j')
        state = s.state()
        assert state['which_key'] is None and state['list_cur'] == 0  # Any key only closes it.


async def test_which_key_and_g_prefix():
    async with ui_session() as s:
        await s.keys('?')
        text = s.text()
        assert s.state()['which_key'] == 'all'
        for expected in ('Keys right now · any key closes', 'LAYERS', 'down one layer / do it', 'up one layer',
                         'MOVE', 'pick an entry', 'GO', 'search everything', ':log', 'all activity', 'HELP',
                         'all keys right now', 'undo in this tab (or reopen a closed tab)'):  # Too long for a column.
            assert expected in text, expected
        assert 'esc tab row' not in s.footer()  # The esc / enter labels hide under the popup.
        await s.shot('which-key', expect='bottom right, above the footer: "Keys right now · any key closes", '
                     'then LAYERS / MOVE / GO / HELP with their keys in two columns (enter down one layer / do it, '
                     'esc up one layer …)')
        await s.keys('x')
        state = s.state()
        assert state['which_key'] is None and state['tabs'] == [] and 'Keys right now' not in s.text()

        await s.keys('enter', '0', 'j', 'enter')  # /chatter and /counter open, /counter active.
        await s.keys('?')
        text = s.text()
        for expected in ('DO (ONLY THESE SEND)', 'start / stop echo', 'echo ⇄ publish', 'INSPECT'):
            assert expected in text, expected
        await s.shot('which-key-entry', expect='? inside /counter (Echo): the keys for an entry, with '
                     'DO (ONLY THESE SEND) space start / stop echo, DO, INSPECT')
        await s.keys('escape')
        assert s.state()['which_key'] is None and s.state()['layer'] == 'in'  # esc only closed it.

        await s.keys('0', 'g')
        state = s.state()
        assert (state['pending'], state['which_key']) == ('g', 'g')
        assert 'g…' in s.footer()
        text = s.text()
        for expected in ('g …  waiting for the next key', 'gg', 'to the top', 'gt', 'next tab', 'gT',
                         'previous tab'):
            assert expected in text, expected
        assert 'LAYERS' not in text
        await s.shot('g-prefix', expect='the narrow g popup bottom right: "g …  waiting for the next key", '
                     'GO gg to the top, gt next tab, gT previous tab; the footer shows "g…" after NORMAL')
        await s.keys('t')
        state = s.state()
        assert (state['pending'], state['which_key'], state['active']) == ('', None, 0)
        assert tuple(state['log']) == ('gt', 'tab 1: /chatter') and 'g…' not in s.footer()

        await s.keys('g', 'escape')
        state = s.state()
        assert (state['pending'], state['layer'], tuple(state['log'])) == ('', 'in', ('esc', 'g canceled'))


async def test_log_view():
    async with ui_session() as s:
        await s.keys(':', 'l', 'o', 'g', 'enter')
        assert s.state()['overlay'] == 'LogView' and 'All activity' in s.text() and s.line_with('│ nothing yet ')
        await s.shot('log-empty', expect='the :log box over the dimmed list: "All activity (0)  j k move · '
                     'enter goes there", then "nothing yet"')
        await s.keys('escape')
        assert s.state()['overlay'] is None

        # Put activity lines in the model directly, newest first.
        nav = s.app.nav
        for tab, text, cls in ((Tab('topics', '/chatter'), '▶ published once', ''),
                               (Tab('actions', '/fibonacci'), '▶ goal sent · order: 12', ''),
                               (Tab('services', '/add_two_ints'), '▶ called · a: 19, b: 23', ''),
                               (Tab('services', '/add_two_ints'), '✓ response · sum: 42 (4.0 ms)', 'g'),
                               (Tab('actions', '/fibonacci'), '✗ goal rejected', 'r')):
            nav.feedback.add_activity(tab, text, cls)
        s.app.refresh_views()
        await s.keys(':', 'l', 'o', 'g', 'enter')
        text = s.text()
        assert 'All activity (5)' in text
        for expected in ('✗ goal rejected', '✓ response · sum: 42 (4.0 ms)', '▶ called · a: 19, b: 23',
                         '▶ goal sent · order: 12', '▶ published once'):
            assert expected in text, expected
        assert ' NORMAL ' in s.footer() and 'esc close' in s.footer() and 'enter go there' in s.footer()
        await s.shot('log-view', expect='the :log box with 5 lines, newest first: ▷ /fibonacci ✗ goal rejected '
                     '(red, picked), ⇄ /add_two_ints ✓ response (green), ▶ called, ▷ /fibonacci ▶ goal sent, '
                     '≋ /chatter ▶ published once; footer NORMAL, esc close, enter go there')

        await s.keys('j', 'j', 'k', 'G', 'g', 'j', 'j')
        assert '▍' in s.line_with('▶ called · a: 19, b: 23')
        await s.shot('log-picked', expect='j j: the third line, ⇄ /add_two_ints ▶ called · a: 19, b: 23, is picked')
        await s.keys('enter')
        state = s.state()
        assert state['overlay'] is None and state['tabs'] == ['/add_two_ints'] and state['active'] == 0
        assert state['path'] == ['tabs', '/add_two_ints'] and 'All activity' not in s.text()
        await s.shot('log-went-there', expect='enter went to the line\'s entry: /add_two_ints open as tab 1')


async def test_close_tab_toast():
    async with ui_session() as s:
        await s.keys('enter', 'x')
        toast = 'closed /chatter · u undoes'
        assert s.state()['toast'] == [toast, 'info']
        assert s.line_with(toast).rstrip().endswith(toast)  # Bottom right of the body.
        await s.shot('toast-info', expect=f'a blue info toast bottom right of the body: "{toast}"; the ☰ list is '
                     'back')
