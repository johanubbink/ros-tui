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

"""The keymap table (ros_tui/ui/keymap.py) against the design's keyList(), and its contract with nav.py."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from harness.nav_world import RowsProvider, nav_after
from ros_tui.ui import keymap
from ros_tui.ui.keymap import ANY, KEYMAP, PREDICATES, TYPE, KeyRow, keys_now, normalize_key, which_key_items
from ros_tui.ui.nav import ACTIONS

REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / 'docs' / 'design' / 'hybrid-keys.html'
INBOX = ['j', 'j', 'j', 'enter']

# keyList() rows whose key or label is computed, as (group, key, label) per case.
DYNAMIC_ROWS = [
    ('Helper', 'j k ↑ ↓', 'next option / way to enter it'),
    ('Helper', 'tab', 'next option / way to enter it'),
    ('Helper', '0–3', 'jump / next field'),
    ('Helper', '↑ ↓', 'jump / next field'),
    ('Insert', '^s', 'keep it and set it'),
    ('Insert', '^s', 'keep it and send'),
    ('Do (only these send)', 'space', 'start / stop echo'),
    ('Do (only these send)', 'space', 'publish once'),
    ('Do (only these send)', 'space', 'call'),
    ('Do (only these send)', 'space', 'send goal'),
    ('Do (only these send)', 'space', 'set changed parameters'),
    ('Do', 'r', 'repeat at {rate} Hz'),
    ('Edit', 'f', 'fill it with the {helper} helper'),
]
DROPPED = ('.',)  # The user dropped "resend the last send".


def design_key_rows():
    """Every literal [group, key, what, …] row in the design's keyList()."""
    html = DESIGN.read_text(encoding='utf-8')
    body = html[html.index('function keyList()'):html.index('function renderKeys()')]
    return set(re.findall(r"\['([^']*)','([^']*)','([^']*)'[,\]]", body))


def table_rows():
    return {(b.group, b.show, b.label) for b in KEYMAP if b.show}


def test_every_design_key_is_in_the_table():
    design = design_key_rows()
    assert len(design) >= 40  # The regex still finds the list.
    missing = {row for row in design if row[1] not in DROPPED} - table_rows()
    assert not missing


def test_computed_design_rows_are_in_the_table():
    assert not set(DYNAMIC_ROWS) - table_rows()


def test_resend_is_gone():
    assert ('Do (only these send)', '.', 'resend the last send') in design_key_rows()  # Still in the design.
    for binding in KEYMAP:
        assert binding.show != '.' and 'resend' not in binding.label
        for keys, _ in binding.run:
            assert '.' not in keys


def test_only_space_and_ctrl_s_dispatch_the_primary_verb():
    keys = {key for b in KEYMAP for ks, action in b.run if action == 'primary' for key in ks}
    assert keys == {'space', 'ctrl+s'}
    send_group = [b for b in KEYMAP if b.group == keymap.SEND and b.show]
    assert {b.show for b in send_group} == {'space'}


def test_every_action_and_predicate_exists():
    for binding in KEYMAP:
        assert binding.mode in keymap.MODES
        for name in binding.when + binding.shown:
            assert name.lstrip('!') in PREDICATES
        for _, action in binding.run:
            assert action in ACTIONS
    used = {action for b in KEYMAP for _, action in b.run}
    assert set(ACTIONS) == used  # No orphan actions either.


SAMPLE_STATES = [
    [], ['escape'], ['enter'], ['enter', 'enter'], INBOX, INBOX + ['enter'], INBOX + ['i'],
    ['/'], [':'], ['g'], ['?'], [':', 'l', 'o', 'g', 'enter'], ['G', 'k', 'enter'], ['G', 'k', 'enter', 'enter'],
    ['/', 'a', 'd', 'd', 'enter'], ['/', 'f', 'i', 'b', 'enter', 'l', 'enter'], ['/', 'r', 'a', 't', 'e'],
]


@pytest.mark.parametrize('keys', SAMPLE_STATES, ids=[' '.join(k) or 'start' for k in SAMPLE_STATES])
def test_no_key_has_two_meanings(keys):
    """Dispatch takes the first matching row; any other row that matches must agree with it."""
    nav = nav_after(keys, RowsProvider())
    mode = nav.input_mode()
    candidates = {key for b in KEYMAP for ks, _ in b.run for key in ks} - {TYPE, ANY} | {'a', 'z', 'space'}
    for key in candidates:
        actions = {action for b in KEYMAP if b.mode == mode and keymap.holds(nav, b.when)
                   for ks, action in b.run
                   if key in ks or ANY in ks or TYPE in ks and keymap.key_char(key) is not None}
        assert len(actions) <= 1, (mode, key, actions)


def rows(nav):
    return [(row.group, row.keys, row.label) for row in keys_now(nav)]


GO = [('Go', '/', 'search everything'), ('Go', ':log', 'all activity'), ('Go', ':', 'command line'),
      ('Go', '0 1…9', '☰ list / tab N'), ('Go', 'H L', 'previous / next tab'), ('Go', 'x', 'close the tab'),
      ('Go', 'u', 'undo in this tab (or reopen a closed tab)')]
LAYERS = [('Layers', 'enter', 'down one layer / do it'), ('Layers', 'esc', 'up one layer')]
HELP = [('Help', '?', 'all keys right now')]


def test_keys_now_on_the_list():
    assert rows(nav_after([])) == LAYERS + [
        ('Move', 'j k', 'pick an entry'), ('Move', 'gg G', 'top / bottom'), ('Move', 'tab', 'filter by kind')] + GO + HELP


def test_keys_now_on_the_tab_row():
    assert rows(nav_after(['escape'])) == LAYERS + [('Move', 'h l', 'previous / next tab')] + GO + HELP


def test_keys_now_in_a_publish_topic():
    assert rows(nav_after(INBOX)) == LAYERS + [
        ('Edit', 'i', 'edit the field under the cursor'), ('Edit', 'c', 'clear it and edit')] + GO + [
        ('Do (only these send)', 'space', 'publish once'),
        ('Do', 'r', 'repeat at 10 Hz'), ('Do', 'R', 'change the repeat rate'), ('Do', 's', 'stop repeating'),
        ('Do', 'e', 'echo ⇄ publish'), ('Do', 'y  p', 'copy / paste a message'), ('Do', '[ ]', 'older / newer sends'),
    ] + HELP


def test_keys_now_inside_an_echo():
    assert rows(nav_after(['enter', 'enter'])) == LAYERS + [
        ('Move', 'j k', 'pick a field or row'), ('Move', 'gg G', 'first / last'),
        ('Edit', 'enter', 'show / hide the field')] + GO + [
        ('Do (only these send)', 'space', 'start / stop echo'), ('Do', 'e', 'echo ⇄ publish'),
        ('Do', 'y  p', 'copy / paste a message'), ('Inspect', 'esc', 'out again: values go live'),
    ] + HELP


def test_keys_now_on_a_node():
    assert rows(nav_after(['G', 'k', 'enter'])) == LAYERS + [('Move', 'h j k l', 'pick an area')] + GO + [
        ('Do (only these send)', 'space', 'set changed parameters'), ('Do', 'u', 'undo a parameter change')] + HELP


def test_keys_now_on_a_helper_row():
    assert ('Edit', 'f', 'fill it with the Quaternion helper') in rows(
        nav_after(INBOX + ['enter', 'j', 'j'], RowsProvider()))


def test_keys_now_in_overlays():
    assert rows(nav_after(['/'])) == [('Search', 'type', 'find by name or type'), ('Search', '↑ ↓', 'pick'),
                                      ('Search', 'enter', 'open in a tab'), ('Search', 'esc', 'close')]
    assert rows(nav_after([':'])) == [('Command', 'type', 'a command, e.g. rate 5'), ('Command', 'tab', 'complete'),
                                      ('Command', 'enter', 'run'), ('Command', 'esc', 'cancel')]
    assert [r[1] for r in rows(nav_after([':', 'l', 'o', 'g', 'enter']))] == ['j k', 'gg G', 'enter', 'esc']
    assert rows(nav_after(INBOX + ['i'], RowsProvider())) == [
        ('Insert', 'type', 'change the value'), ('Insert', 'esc / enter', 'keep it, back to normal'),
        ('Insert', 'tab', 'keep it, edit the next field'), ('Insert', '^s', 'keep it and send')]


def test_aliases():
    by_label = {row.label: row for row in keys_now(nav_after([]))}
    assert by_label['pick an entry'].alias == '↑ ↓'
    assert by_label['search everything'].alias == '^f'
    assert by_label['previous / next tab'].alias == 'gT gt'


def test_which_key_lists():
    nav = nav_after(['g'])
    assert which_key_items(nav) == [KeyRow('Go', 'gg', 'to the top', ''), KeyRow('Go', 'gt', 'next tab', ''),
                                    KeyRow('Go', 'gT', 'previous tab', '')]
    nav = nav_after(['?'])
    assert which_key_items(nav) == keys_now(nav) == keys_now(nav_after([]))


@pytest.mark.parametrize('name, canonical', [
    ('slash', '/'), ('/', '/'), ('colon', ':'), ('question_mark', '?'), ('?', '?'),
    ('left_square_bracket', '['), ('right_square_bracket', ']'), ('full_stop', '.'),
    ('G', 'G'), ('shift+g', 'G'), ('j', 'j'), (' ', 'space'), ('space', 'space'), ('esc', 'escape'),
    ('escape', 'escape'), ('enter', 'enter'), ('tab', 'tab'), ('shift+tab', 'shift+tab'), ('ctrl+s', 'ctrl+s'),
    ('up', 'up'), ('backspace', 'backspace'), ('delete', 'delete'), ('f5', 'f5'), ('plus_sign', '+'),
])
def test_normalize_key(name, canonical):
    assert normalize_key(name) == canonical


def test_pure_python():
    """nav.py and keymap.py import neither textual nor rclpy."""
    code = ('import sys; import ros_tui.ui.nav, ros_tui.ui.keymap; '
            'print(sorted({m.split(".")[0] for m in sys.modules} & {"textual", "rclpy", "rich"}))')
    out = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == '[]'


def test_export_script(tmp_path):
    target = tmp_path / 'keymap.json'
    subprocess.run([sys.executable, str(REPO / 'scripts' / 'export_keymap.py'), str(target)], check=True)
    data = json.loads(target.read_text(encoding='utf-8'))
    assert len(data['bindings']) == len(KEYMAP)
    assert {'name': 'q', 'text': 'quit'} in data['commands']
    out = subprocess.run([sys.executable, str(REPO / 'scripts' / 'export_keymap.py')],
                         capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == data
