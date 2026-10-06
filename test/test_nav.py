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

"""The nav model (ros_tui/ui/nav.py) against the design prototype's keydown handler.

Each scripted sequence's expectations were worked out by reading docs/design/hybrid-keys.html
(goUp / goDown / activate / openEntity / closeTab / undo / stepTab / the keydown handler and the
footer helpers modeName / pathParts / upLabel / downLabel), in its world (harness.nav_world).
"""

import pytest
from harness.fake_bridge import DEMO_GRAPH
from harness.nav_world import DESIGN_CATALOG, DesignProvider, RowsProvider, design_nav, nav_after
from ros_tui.constants import NAV_ERRLINE_S, NAV_TOAST_S
from ros_tui.ui.nav import AREA, EDIT, IN, TABS, Helper, NavState, Tab, short_type

HOME = ('tabs', '☰ list')
OPEN3 = ['enter', '0', 'j', 'enter', '0', 'j', 'enter']  # /chatter, /counter, /diagnostic_status.
THREE = ['/chatter', '/counter', '/diagnostic_status']
INBOX = ['j', 'j', 'j', 'enter']  # /inbox: nobody publishes it, so it opens in Publish.


def state(layer, active, tabs, path, mode='normal', esc=None, enter=None):
    expected = {'layer': layer, 'active': active, 'tabs': tabs, 'path': list(path), 'mode': mode}
    if esc is not None:
        expected['esc'] = esc
    if enter is not None:
        expected['enter'] = enter
    return expected


SEQUENCES = [
    # esc / enter on every layer
    ('start', [], state(IN, -1, [], HOME, esc='tab row', enter='open /chatter')),
    ('esc to the tab row', ['escape'], state(TABS, -1, [], ['tabs'], esc='', enter='go in')),
    ('esc on the top layer stays', ['escape', 'escape'], state(TABS, -1, [], ['tabs'], esc='', enter='go in')),
    ('enter from the tab row goes in', ['escape', 'enter'], state(IN, -1, [], HOME)),
    ('enter opens the list row', ['enter'],
     state(IN, 0, ['/chatter'], ['tabs', '/chatter'], esc='tab row', enter='into latest message')),
    ('enter goes into the area', ['enter', 'enter'],
     state(AREA, 0, ['/chatter'], ['tabs', '/chatter', 'latest message'], esc='back out', enter='show / hide field')),
    ('esc out of the area', ['enter', 'enter', 'escape'], state(IN, 0, ['/chatter'], ['tabs', '/chatter'])),
    ('esc esc to the tab row', ['enter', 'enter', 'escape', 'escape'],
     state(TABS, 0, ['/chatter'], ['tabs'], esc='', enter='go in')),
    ('back in from the tab row', ['enter', 'escape', 'enter'], state(IN, 0, ['/chatter'], ['tabs', '/chatter'])),
    ('a topic nobody publishes opens in publish', INBOX,
     state(IN, 0, ['/inbox'], ['tabs', '/inbox'], enter='into message')),
    ('enter into the message', INBOX + ['enter'],
     state(AREA, 0, ['/inbox'], ['tabs', '/inbox', 'message'], esc='back out', enter='edit')),
    # search opens, then the area pick of a two-area entry
    ('search opens a tab', ['/', 'a', 'd', 'd', 'enter'],
     state(IN, 0, ['/add_two_ints'], ['tabs', '/add_two_ints'], enter='into request')),
    ('l picks the next area', ['slash', 'a', 'd', 'd', 'enter', 'l'],
     state(IN, 0, ['/add_two_ints'], ['tabs', '/add_two_ints'], enter='into response')),
    ('tab wraps the area pick', ['/', 'a', 'd', 'd', 'enter', 'l', 'tab'],
     state(IN, 0, ['/add_two_ints'], ['tabs', '/add_two_ints'], enter='into request')),
    ('two areas: esc picks another', ['/', 'a', 'd', 'd', 'enter', 'down', 'enter'], state(
        AREA, 0, ['/add_two_ints'], ['tabs', '/add_two_ints', 'response'], esc='pick another area', enter='')),
    # digits
    ('three tabs', OPEN3, state(IN, 2, THREE, ['tabs', '/diagnostic_status'])),
    ('1 goes to tab 1', OPEN3 + ['1'], state(IN, 0, THREE, ['tabs', '/chatter'])),
    ('3 goes to tab 3', OPEN3 + ['1', '3'], state(IN, 2, THREE, ['tabs', '/diagnostic_status'])),
    ('4 is no tab', OPEN3 + ['4'], state(IN, 2, THREE, ['tabs', '/diagnostic_status'])),
    ('0 is the list', OPEN3 + ['0'], state(IN, -1, THREE, HOME, enter='open /diagnostic_status')),
    ('a digit from the tab row', OPEN3 + ['escape', '2'], state(IN, 1, THREE, ['tabs', '/counter'])),
    # H / L and gt / gT wrap through the list
    ('L wraps to the list', OPEN3 + ['L'], state(IN, -1, THREE, HOME)),
    ('L L wraps to tab 1', OPEN3 + ['L', 'L'], state(IN, 0, THREE, ['tabs', '/chatter'])),
    ('H', OPEN3 + ['H'], state(IN, 1, THREE, ['tabs', '/counter'])),
    ('H from the list wraps to the last', OPEN3 + ['0', 'H'], state(IN, 2, THREE, ['tabs', '/diagnostic_status'])),
    ('gt', OPEN3 + ['1', 'g', 't'], state(IN, 1, THREE, ['tabs', '/counter'])),
    ('gT', OPEN3 + ['1', 'g', 'T'], state(IN, -1, THREE, HOME)),
    ('shift+l is L', OPEN3 + ['1', 'shift+l'], state(IN, 1, THREE, ['tabs', '/counter'])),
    # gg / G
    ('G on the list', ['G'], state(IN, -1, [], HOME, enter='open /talker')),
    ('gg on the list', ['G', 'g', 'g'], state(IN, -1, [], HOME, enter='open /chatter')),
    # x then u reopens at the same position
    ('x closes the active tab', OPEN3 + ['2', 'x'], state(IN, 1, ['/chatter', '/diagnostic_status'],
                                                          ['tabs', '/diagnostic_status'])),
    ('u reopens it in place', OPEN3 + ['2', 'x', 'u'], state(IN, 1, THREE, ['tabs', '/counter'])),
    ('x on the last tab', OPEN3 + ['x'], state(IN, 1, ['/chatter', '/counter'], ['tabs', '/counter'])),
    ('u from another tab reopens', OPEN3 + ['2', 'x', '1', 'u'], state(IN, 1, THREE, ['tabs', '/counter'])),
    ('x on the tab row closes the cursor tab', OPEN3 + ['escape', 'h', 'x'],
     state(TABS, 1, ['/chatter', '/diagnostic_status'], ['tabs'])),
    ('x on the list keeps it', ['x'], state(IN, -1, [], HOME)),
    (':close', ['enter', ':', 'c', 'l', 'o', 'enter'], state(IN, -1, [], HOME)),
    # chips
    ('tab filters topics', ['tab'], state(IN, -1, [], HOME, enter='open /chatter')),
    ('tab tab filters services', ['tab', 'tab'], state(IN, -1, [], HOME, enter='open /add_two_ints')),
    ('shift+tab filters nodes', ['shift+tab'], state(IN, -1, [], HOME, enter='open /ros_tui_demo_servers')),
    # overlays restore the exact layer
    ('search esc back in the area', ['enter', 'enter', '/', 'c', 'h', 'escape'],
     state(AREA, 0, ['/chatter'], ['tabs', '/chatter', 'latest message'], esc='back out')),
    ('^f esc back on the tab row', ['enter', 'escape', 'ctrl+f', 'x', 'escape'],
     state(TABS, 0, ['/chatter'], ['tabs'])),
    ('search mode hides esc / enter', ['/'], state(IN, -1, [], HOME, mode='search', esc='', enter='')),
    ('search: down picks the second match', ['/', 'p', 'o', 's', 'e', 'down', 'enter'],
     state(IN, 0, ['/goal_pose'], ['tabs', '/goal_pose'])),
    ('search: ^n ^p', ['/', 'p', 'o', 's', 'e', 'ctrl+n', 'ctrl+n', 'ctrl+p', 'enter'],
     state(IN, 0, ['/goal_pose'], ['tabs', '/goal_pose'])),
    ('search: an open tab is gone to', ['enter', '0', '/', 'c', 'h', 'a', 't', 'enter'],
     state(IN, 0, ['/chatter'], ['tabs', '/chatter'])),
    ('command mode', [':'], state(IN, -1, [], HOME, mode='command')),
    (':topics from a tab', ['enter', ':', 't', 'tab', 'enter'], state(IN, -1, ['/chatter'], HOME)),
    ('which-key closes on any key', ['?', 'j'], state(IN, -1, [], HOME, enter='open /chatter')),
    ('g then a wrong key does nothing', ['g', 'j'], state(IN, -1, [], HOME, enter='open /chatter')),
    # found by the verifier against the prototype
    ('x on the only tab goes to the list', ['enter', 'x'], state(IN, -1, [], HOME)),
    ('u after x on the tab row goes in', OPEN3 + ['escape', 'h', 'x', 'u'], state(IN, 1, THREE, ['tabs', '/counter'])),
    ('H on the tab row steps from the active tab', OPEN3 + ['escape', 'h', 'h', 'H'],
     state(IN, 1, THREE, ['tabs', '/counter'])),
    ('a digit with no tabs open', ['9'], state(IN, -1, [], HOME)),
    ('? then x only closes the popup', ['enter', '?', 'x'], state(IN, 0, ['/chatter'], ['tabs', '/chatter'])),
    ('g esc stays in the area', ['enter', 'enter', 'g', 'escape'],
     state(AREA, 0, ['/chatter'], ['tabs', '/chatter', 'latest message'])),
    (': esc back in the area', ['enter', 'enter', ':', 'x', 'escape'],
     state(AREA, 0, ['/chatter'], ['tabs', '/chatter', 'latest message'])),
]


@pytest.mark.parametrize('keys, expected', [s[1:] for s in SEQUENCES], ids=[s[0] for s in SEQUENCES])
def test_sequence(keys, expected):
    summary = nav_after(keys).summary()
    assert {key: summary[key] for key in expected} == expected


def test_enough_sequences():
    assert len(SEQUENCES) >= 25


def last_log(nav):
    return nav.log[0]


def test_open_and_went_to_messages():
    nav = nav_after(['enter'])
    assert last_log(nav) == ('enter', 'opened /chatter (tab 1)')
    nav.handle_key('0')
    assert last_log(nav) == ('0', '☰ the list')
    nav.handle_key('enter')
    assert last_log(nav) == ('enter', 'went to /chatter (tab 1)')
    assert nav.tabs == [nav.tab]


def test_layer_log_lines():
    nav = nav_after(['enter', 'enter'])
    assert last_log(nav) == ('enter', 'inside latest message')
    nav.handle_key('escape')
    assert last_log(nav) == ('esc', 'up one layer')
    nav.handle_key('escape')
    assert last_log(nav) == ('esc', 'up to the tab row')
    nav.handle_key('escape')
    assert last_log(nav) == ('esc', 'top layer — :q quits')


def test_digit_without_a_tab():
    assert last_log(nav_after(OPEN3 + ['4'])) == ('4', 'no tab 4')


def test_tab_row_cursor_with_no_tabs_stays_on_the_list():
    nav = nav_after(['escape', 'l'])
    assert nav.tab_cur == -1
    nav.handle_key('h')
    assert nav.tab_cur == -1


def test_g_prefix_logs_the_whole_key():
    assert last_log(nav_after(OPEN3 + ['1', 'g', 't'])) == ('gt', 'tab 2: /counter')
    assert last_log(nav_after(OPEN3 + ['1', 'L'])) == ('L', 'tab 2: /counter')


def test_tab_row_cursor_wraps():
    nav = nav_after(['enter', '0', 'j', 'enter', 'escape'])
    assert (nav.layer, nav.tab_cur) == (TABS, 1)
    cursors = []
    for key in ['l', 'l', 'right', 'tab', 'h', 'left', 'shift+tab']:
        nav.handle_key(key)
        cursors.append(nav.tab_cur)
    assert cursors == [-1, 0, 1, -1, 1, 0, -1]
    assert last_log(nav) == ('esc', 'up to the tab row')  # Moving on the tab row logs nothing.
    nav.handle_key('G')
    assert nav.tab_cur == 1
    nav.handle_key('g')
    nav.handle_key('g')
    assert nav.tab_cur == -1
    nav.handle_key('enter')
    assert (nav.layer, nav.active) == (IN, -1)


def test_close_toasts_and_undo_reopens():
    nav = nav_after(OPEN3 + ['2', 'x'])
    assert last_log(nav) == ('x', 'closed /counter — u reopens it')
    assert (nav.toast.text, nav.toast.kind) == ('closed /counter · u undoes', 'info')
    nav.handle_key('u')
    assert last_log(nav) == ('u', 'reopened /counter')
    nav.handle_key('u')
    assert last_log(nav) == ('u', 'nothing to undo here')
    assert (nav.toast.text, nav.toast.kind) == ('nothing to undo here', 'info')


def test_toast_expires_on_the_clock():
    now = [10.0]
    nav = design_nav()
    nav.clock = lambda: now[0]
    nav.handle_key(':')
    for key in 'foo':
        nav.handle_key(key)
    nav.handle_key('enter')
    assert nav.toast.until == pytest.approx(10.0 + NAV_TOAST_S)
    now[0] += NAV_TOAST_S - 0.1
    assert not nav.tick() and nav.toast is not None
    now[0] += 0.1
    assert nav.tick() and nav.toast is None
    assert not nav.tick()


def test_errline_expires_on_the_clock():
    now = [10.0]
    nav = rows_nav(INBOX + ['enter', 'c', 'x'])
    nav.clock = lambda: now[0]
    nav.handle_key('enter')
    inbox = Tab('topics', '/inbox')
    assert nav.errline(inbox) and nav.layer == EDIT
    now[0] += NAV_ERRLINE_S - 0.1
    assert not nav.tick() and nav.errline(inbox)
    now[0] += 0.1
    assert nav.tick() and nav.errline(inbox) == '' and nav.layer == EDIT


@pytest.mark.parametrize('kind, type_name, short', [
    ('topics', 'std_msgs/msg/String', 'String'),
    ('services', 'turtlesim/srv/TeleportAbsolute', 'TeleportAbsolute'),
    ('nodes', 'namespace /', 'node'),
])
def test_short_type(kind, type_name, short):
    assert short_type(kind, type_name) == short


def test_x_on_the_list():
    assert last_log(nav_after(['x'])) == ('x', 'the ☰ list always stays')


def test_close_then_reopen_when_it_was_opened_again():
    nav = nav_after(OPEN3 + ['2', 'x', '0', 'k', 'enter', '1', 'u'])
    assert [t.name for t in nav.tabs] == ['/chatter', '/diagnostic_status', '/counter']
    assert nav.tab.name == '/counter'  # Already open again, so u just goes there.


def test_chips_cycle_and_reset_the_cursor():
    nav = nav_after(['j', 'j'])
    seen = []
    for key in ['tab'] * 5:
        nav.handle_key(key)
        seen.append((nav.chip, last_log(nav)[1], nav.list_cur))
    assert seen == [(0, 'showing topics', 0), (1, 'showing services', 0), (2, 'showing actions', 0),
                    (3, 'showing nodes', 0), (-1, 'showing everything', 0)]
    nav.handle_key('shift+tab')
    assert (nav.chip, len(nav.home_rows())) == (3, 2)
    assert last_log(nav) == ('shift+tab', 'showing nodes')


def test_list_cursor_clamps():
    nav = nav_after(['k', 'up'])
    assert nav.list_cur == 0
    nav = nav_after(['j'] * 30)
    assert nav.list_cur == len(nav.home_rows()) - 1 == 11


def test_unknown_key_hints():
    assert last_log(nav_after(['z'])) == ('z', 'nothing on "z" here — ? shows the keys')
    assert last_log(nav_after(['enter', 'enter', 'z'])) == ('z', 'nothing on "z" here — ? shows the keys')
    nav = nav_after(['escape', 'z'])  # The tab row ignores keys it doesn't use.
    assert last_log(nav) == ('esc', 'up to the tab row')


def test_unwanted_keys_are_not_consumed():
    nav = design_nav()
    assert nav.handle_key('f5') is False
    assert nav.handle_key('j') is True


# ---------- search ----------

def test_search_type_move_open():
    nav = nav_after(['/'])
    assert last_log(nav) == ('/', 'search everything')
    for key in 'pose':
        nav.handle_key(key)
    assert [item.name for _, item in nav.search_rows()] == [
        '/localisation_pose', '/goal_pose', '/set_pose', '/navigate_to_pose']
    nav.handle_key('up')
    assert nav.search.cur == 0
    for key in ['down'] * 9:
        nav.handle_key(key)
    assert nav.search.cur == 3
    nav.handle_key('backspace')
    assert (nav.search.q, nav.search.cur) == ('pos', 0)
    nav.handle_key('enter')
    assert nav.search is None and nav.tab.name == '/localisation_pose'
    assert last_log(nav) == ('enter', 'opened /localisation_pose (tab 1)')


def test_search_matches_types_and_keeps_typing_keys():
    nav = nav_after(['/', 'A', 'd', 'd', 'T', 'w', 'o'])  # In the type, case-insensitive.
    assert [item.name for _, item in nav.search_rows()] == ['/add_two_ints']
    nav = nav_after(['/', 'x', 'space', 'q', 'question_mark'])  # Keys that mean something in normal mode type.
    assert nav.search.q == 'x q?' and nav.which_key is None and nav.tabs == []


def test_search_without_matches_stays_open():
    nav = nav_after(['/', 'z', 'z', 'z', 'enter'])
    assert nav.search is not None and nav.tabs == []


def test_search_esc_message():
    assert last_log(nav_after(['/', 'escape'])) == ('esc', 'search closed — back where you were')


# ---------- command line ----------

def suggestions(nav):
    return [name for name, _ in nav.cmd_suggestions()]


def test_command_suggestions_and_tab_completion():
    nav = nav_after([':'])
    assert suggestions(nav) == ['log', 'topics', 'services', 'actions', 'nodes', 'all', 'rate ']
    nav.handle_key('a')
    assert suggestions(nav) == ['actions', 'all']
    nav.handle_key('shift+tab')  # The design reads shift+tab as tab here too.
    assert nav.cmd.q == 'actions'
    nav = nav_after([':', 'r', 'tab'])
    assert nav.cmd.q == 'rate '
    nav.handle_key('5')
    assert suggestions(nav) == ['rate ']
    nav.handle_key('tab')  # Nothing to complete once an argument is typed.
    assert nav.cmd.q == 'rate 5'


@pytest.mark.parametrize('keys, chip', [
    ([':', 't', 'tab', 'enter'], 0),
    ([':', 's', 'e', 'enter'], 1),  # A partial word runs the first suggestion.
    ([':', 'a', 'enter'], 2),
    ([':', 'a', 'l', 'l', 'enter'], -1),
    ([':', 'n', 'o', 'd', 'e', 's', 'enter'], 3),
    ([':', 'down', 'down', 'enter'], 1),  # ↑↓ picks a suggestion, enter runs it.
])
def test_list_commands(keys, chip):
    nav = nav_after(['enter', 'escape'] + keys)
    assert (nav.chip, nav.active, nav.layer, nav.list_cur, nav.cmd) == (chip, -1, IN, 0, None)


def test_topics_command_message():
    nav = nav_after([':', 't', 'o', 'p', 'i', 'c', 's', 'enter'])
    assert last_log(nav) == (':topics', '☰ lists topics')
    nav = nav_after([':', 'a', 'l', 'l', 'enter'])
    assert last_log(nav) == (':all', '☰ lists everything')


def test_unknown_command_toasts():
    nav = nav_after([':', 'f', 'o', 'o', 'enter'])
    assert (nav.toast.text, nav.toast.kind) == ('unknown command :foo — : then tab lists them', 'bad')
    assert last_log(nav) == (':foo', 'unknown command')
    assert nav.cmd is None


def test_command_with_an_argument_stays_open():
    nav = nav_after([':', 'up', 'enter'])  # Up wraps to the last suggestion, 'rate '.
    assert nav.cmd is not None and nav.cmd.q == 'rate '
    nav = nav_after(['/', 'i', 'n', 'b', 'enter', ':', 'r', 'tab', 'enter', '5', 'enter'], RowsProvider())
    assert nav.cmd is None
    assert nav.provider.verbs[-1] == ('set_rate', ':rate', '5')


def test_command_word_without_its_argument_runs():
    nav = nav_after(['/', 'i', 'n', 'b', 'enter', ':', 'r', 'a', 't', 'e', 'enter'], RowsProvider())
    assert nav.cmd is None and nav.provider.verbs[-1] == ('set_rate', ':rate', '')
    nav = nav_after([':', 'r', 'a', 'enter'])  # A partial word picks 'rate ', which waits for its argument.
    assert nav.cmd.q == 'rate '


def test_command_line_opens_empty_each_time():
    nav = nav_after([':', 'x', 'escape', ':'])
    assert nav.cmd.q == ''


def test_command_cancel():
    for keys in ([':', 'escape'], [':', 'backspace'], [':', 'x', 'backspace', 'backspace']):
        nav = nav_after(keys)
        assert nav.cmd is None and nav.footer().mode == 'normal'
    nav = nav_after([':', 'x', 'y', 'backspace'])
    assert nav.cmd.q == 'x'


def test_other_commands():
    assert nav_after([':', 'q', 'enter']).quit
    assert nav_after([':', 'h', 'e', 'l', 'p', 'enter']).which_key == 'all'
    nav = nav_after([':', 'l', 'o', 'g', 'enter'])
    assert nav.logv is not None
    nav.handle_key('escape')
    assert nav.logv is None
    nav = nav_after(['/', 'd', 'i', 'a', 'g', 'enter', ':', 'p', 'u', 'b', 'enter'])
    assert (nav.entry_mode(), last_log(nav)) == ('publish', (':pub', 'now in publish'))
    nav.run_command('echo')
    assert nav.entry_mode() == 'echo'
    assert nav_after([':', 'e', 'c', 'h', 'o', 'enter']).log[0] == (':echo', 'only topics have Echo / Publish')


# ---------- popups ----------

def test_which_key_closes_on_the_next_key():
    nav = nav_after(['?'])
    assert nav.which_key == 'all'
    assert nav.footer()[2:4] == ('', '')  # esc / enter are hidden under the popup.
    nav.handle_key('escape')  # Any key just closes it: esc doesn't also go up.
    assert (nav.which_key, nav.layer) == (None, IN)


def test_g_prefix_popup():
    nav = nav_after(['g'])
    assert (nav.pending, nav.which_key, nav.footer().pending) == ('g', 'g', 'g')
    nav.handle_key('j')
    assert (nav.pending, nav.which_key, nav.list_cur) == ('', None, 0)
    assert last_log(nav) == ('gj', 'no such key')
    nav = nav_after(['g', 'escape'])
    assert (last_log(nav), nav.layer) == (('esc', 'g canceled'), IN)


# ---------- the area and insert layers (RowsProvider) ----------

def rows_nav(keys):
    return nav_after(keys, RowsProvider())


def test_rows_move_and_clamp():
    nav = rows_nav(INBOX + ['enter'])
    rows = []
    for key in ['j', 'down', 'j', 'tab', 'k', 'shift+tab', 'up', 'G', 'g', 'g']:
        nav.handle_key(key)
        rows.append(nav.row_index())
    assert rows == [1, 2, 2, 2, 1, 0, 0, 2, 2, 0]
    assert last_log(nav) == ('gg', 'to the top')


def test_rows_are_remembered_per_entry():
    nav = rows_nav(INBOX + ['enter', 'j', '0', 'G', 'enter', 'enter'])  # /talker is a node.
    assert nav.row_index() == 0
    nav.handle_key('1')
    nav.handle_key('enter')
    assert nav.row_index() == 1


def test_edit_and_keep():
    nav = rows_nav(INBOX + ['enter', 'enter'])
    assert (nav.layer, last_log(nav)) == (EDIT, ('enter', 'edit a (insert)'))
    assert nav.summary()['path'] == ['tabs', '/inbox', 'message', 'editing']
    assert nav.footer()[0:4] == ('insert', ('tabs', '/inbox', 'message', 'editing'), 'keep it', 'keep it')
    for key in ['5', 'backspace', '7', 'full_stop', '5']:
        nav.handle_key(key)
    assert nav.editing.value == '17.5'
    nav.handle_key('escape')
    assert (nav.layer, last_log(nav)) == (AREA, ('esc', 'kept a = 17.5 (u undoes)'))


def test_typing_in_insert_doesnt_run_keys():
    nav = rows_nav(INBOX + ['enter', 'c', 'x', 'u', 'g', 'question_mark', 'space', '0'])
    assert nav.editing.value == 'xug? 0'
    assert (nav.tabs[0].name, len(nav.tabs), nav.which_key, nav.pending) == ('/inbox', 1, None, '')


def test_invalid_value_enter_stays_esc_drops():
    nav = rows_nav(INBOX + ['enter', 'c', 'x', 'enter'])
    assert nav.layer == EDIT
    assert last_log(nav) == ('enter', '✗ a needs a number, got "x" — still editing (esc drops it)')
    assert nav.errline(Tab('topics', '/inbox')) == 'a needs a number, got "x"'
    nav.handle_key('escape')
    assert nav.layer == AREA and nav.editing is None
    assert (nav.toast.text, nav.toast.kind) == ('a needs a number, got "x" — kept the old value', 'bad')
    assert last_log(nav) == ('esc', '✗ a needs a number, got "x" — dropped, kept the old value')
    assert 'topics:/inbox' not in nav.errlines
    assert nav.provider.values['topics:/inbox|msg'] == ['1', '2', '3']


def test_tab_keeps_and_edits_the_next_field():
    nav = rows_nav(INBOX + ['enter', 'enter', 'tab'])
    assert (nav.layer, nav.editing.field, nav.row_index()) == (EDIT, 'b', 1)
    nav.handle_key('tab')
    nav.handle_key('tab')  # Stays on the last field.
    assert (nav.editing.field, nav.row_index()) == ('c', 2)
    nav.handle_key('shift+tab')
    assert nav.editing.field == 'b'


def test_i_and_c_from_the_area_pick():
    nav = rows_nav(INBOX + ['i'])
    assert (nav.layer, nav.editing.value) == (EDIT, '1')
    nav = rows_nav(INBOX + ['c'])
    assert (nav.layer, nav.editing.value, last_log(nav)) == (EDIT, '', ('c', 'clear and edit a (insert)'))
    nav = rows_nav(['enter', 'i'])  # The echo's latest message isn't editable.
    assert nav.layer == IN and last_log(nav) == ('i', 'nothing on "i" here — ? shows the keys')


def test_ctrl_s_in_insert_keeps_then_sends():
    nav = rows_nav(INBOX + ['i', '9', 'ctrl+s'])
    assert nav.layer == AREA and nav.provider.verbs == [('primary', '^s', None)]
    assert nav.provider.values['topics:/inbox|msg'][0] == '19'
    nav = rows_nav(INBOX + ['c', 'x', 'ctrl+s'])  # A bad value is never sent.
    assert nav.layer == EDIT and nav.provider.verbs == []


def test_space_sends_only_from_an_entry():
    nav = rows_nav(['space'])
    assert nav.provider.verbs == []
    nav = rows_nav(['enter', 'escape', 'space'])  # Not from the tab row either.
    assert nav.provider.verbs == []
    nav = rows_nav(['enter', 'space', 'enter', 'ctrl+s'])
    assert nav.provider.verbs == [('primary', 'space', None), ('primary', '^s', None)]


def test_verbs_reach_the_provider():
    nav = rows_nav(INBOX + ['s', 'r', 'R', 'left_square_bracket', ']', 'y', 'p'])
    assert [v[0] for v in nav.provider.verbs] == [
        'secondary', 'repeat', 'rate', 'history_older', 'history_newer', 'yank', 'paste']


def test_full_stop_does_nothing():
    nav = rows_nav(INBOX + ['.', 'full_stop'])
    assert nav.provider.verbs == []
    assert last_log(nav) == ('.', 'nothing on "." here — ? shows the keys')


def test_a_verb_nobody_handles_does_nothing():
    assert last_log(nav_after(INBOX + ['space'])) == ('space', 'nothing to do here')
    assert last_log(nav_after(['y'])) == ('y', 'open an entry first')


def test_e_toggles_the_topic_mode():
    nav = nav_after(['enter', 'enter', 'e'])
    assert (nav.entry_mode(), nav.layer, last_log(nav)) == ('publish', IN, ('e', 'now in publish'))
    assert nav.footer().enter == 'into message'


def test_helper_hint_and_f():
    nav = rows_nav(INBOX + ['enter', 'j', 'j'])
    assert nav.footer().helper == 'Quaternion'
    nav = rows_nav(INBOX + ['f'])  # f on a picked message goes in first.
    assert nav.layer == AREA and nav.provider.verbs == [('helper', 'f', None)]
    nav = nav_after(INBOX + ['enter', 'f'])
    assert (nav.toast.text, last_log(nav)) == ('no helper for this field — fields with one show [f …]',
                                               ('f', 'no helper on this field'))


def test_enter_on_an_interface_row_opens_it():
    nav = rows_nav(['G', 'k', 'enter', 'enter', 'enter'])
    assert [t.name for t in nav.tabs] == ['/ros_tui_demo_servers', '/chatter']
    assert (nav.active, nav.layer) == (1, IN)


def test_enter_on_a_plain_row():
    nav = nav_after(['/', 'a', 'd', 'd', 'enter', 'l', 'enter', 'enter'])
    assert last_log(nav) == ('enter', 'nothing to edit here — esc goes back up')


def test_node_footer_labels():
    nav = rows_nav(['G', 'k', 'enter'])
    assert nav.footer().enter == 'into interfaces'
    nav.handle_key('enter')
    assert nav.footer()[2:4] == ('pick another area', 'open it')
    nav.handle_key('escape')
    nav.handle_key('l')
    nav.handle_key('enter')
    assert nav.footer()[1:4] == (('tabs', '/ros_tui_demo_servers', 'parameters'), 'pick another area', 'edit')


def test_helper_overlay_routes_to_the_provider():
    nav = rows_nav(INBOX + ['enter', 'j', 'j'])
    nav.helper = Helper('quat')
    assert nav.footer()[0:4] == ('helper', ('tabs', '/inbox', 'message'), 'cancel', 'apply')
    for key in ['tab', 'j', '9']:  # Everything goes to the helper; nothing moves underneath.
        nav.handle_key(key)
    nav.handle_key('enter')
    assert nav.provider.verbs == [('helper_key', 'tab', 'tab'), ('helper_key', 'j', 'j'), ('helper_key', '9', '9'),
                                  ('helper_apply', 'enter', None)]
    assert (nav.row_index(), nav.layer) == (2, AREA)
    nav.handle_key('escape')
    assert nav.helper is None and last_log(nav) == ('esc', 'helper closed, nothing changed')


# ---------- per-tab undo ----------

def test_undo_is_per_tab():
    nav = rows_nav(INBOX + ['enter', 'enter', '5', 'escape', '0', 'G', 'k', 'enter'])  # Edit /inbox, open a node.
    nav.handle_key('u')
    assert last_log(nav) == ('u', 'nothing to undo here')
    assert nav.provider.values['topics:/inbox|msg'][0] == '15'
    nav.handle_key('1')
    nav.handle_key('u')
    assert last_log(nav) == ('u', 'undid the edit of a on /inbox')
    assert nav.provider.values['topics:/inbox|msg'][0] == '1'


def test_reopen_is_the_global_exception():
    nav = rows_nav(['enter', '0'] + INBOX + ['enter', 'enter', '5', 'escape', '1', 'x'])
    assert [t.name for t in nav.tabs] == ['/inbox']
    nav.handle_key('u')  # From /inbox: its own edit is older than the close.
    assert (last_log(nav), nav.tab.name) == (('u', 'reopened /chatter'), '/chatter')
    nav.handle_key('u')
    assert last_log(nav) == ('u', 'nothing to undo here')


# ---------- activity log ----------

def test_activity_log_moves_and_jumps():
    nav = design_nav()
    nav.open_entity('topics', '/chatter', 'test')
    nav.open_entity('services', '/add_two_ints', 'test')
    nav.add_activity(nav.tabs[0], 'echo started')
    nav.add_activity(nav.tabs[1], '▶ called · a: 1, b: 2')
    nav.handle_key('0')
    nav.run_command('log')
    assert nav.footer()[2:4] == ('close', 'go there')
    for key, cur in [('j', 1), ('j', 1), ('k', 0), ('G', 1), ('g', 0), ('down', 1)]:
        nav.handle_key(key)
        assert nav.logv.cur == cur
    nav.handle_key('enter')
    assert nav.logv is None and nav.tab.name == '/chatter'


# ---------- footer details ----------

def test_breadcrumb_override_for_a_custom_editor():
    nav = rows_nav(INBOX)
    nav.editing = nav.provider.start_edit(nav.tab, nav.area(), 0, False)
    nav.editing.crumb = ('repeat rate',)
    nav.editing.back = IN
    nav.layer = EDIT
    assert nav.path() == ('tabs', '/inbox', 'repeat rate', 'editing')
    nav.handle_key('enter')
    assert nav.layer == IN


def test_set_catalog_from_a_graph_snapshot():
    nav = NavState(DesignProvider())
    nav.set_catalog(DEMO_GRAPH, publishers={'/chatter': 1})
    assert [item.name for _, item in nav.home_rows()][:2] == ['/chatter', '/counter']
    assert nav.catalog['services'][0].type == 'example_interfaces/srv/AddTwoInts'
    nav.handle_key('enter')
    assert nav.entry_mode() == 'echo'
    nav.handle_key('0')
    nav.handle_key('j')
    nav.handle_key('enter')
    assert nav.entry_mode() == 'publish'  # Nobody publishes /counter in this count.


def test_set_catalog_clamps_the_cursor():
    nav = nav_after(['G'])
    nav.set_catalog(type(DESIGN_CATALOG)(topics=DESIGN_CATALOG.topics[:2], services=[], actions=[], nodes=[]))
    assert nav.list_cur == 1
