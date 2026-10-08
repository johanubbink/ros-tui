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

"""The keymap table (ros_tui/ui/keymap.py): its contract with nav.py and with docs/usage.md."""

import subprocess
import sys
from pathlib import Path

import pytest
from harness.nav_world import RowsWorld, nav_after
from ros_tui.ui import keymap
from ros_tui.ui.entries.kinds import KINDS
from ros_tui.ui.keymap import ANY, KEYMAP, PREDICATES, TYPE, KeyRow, keys_now, normalize_key, which_key_items
from ros_tui.ui.nav import ACTIONS, Tab

REPO = Path(__file__).resolve().parents[1]
INBOX = ['j', 'j', 'j', 'enter']


def test_only_space_and_ctrl_s_dispatch_the_primary_verb():
    keys = {key for b in KEYMAP for run in b.run if run.action == 'primary' for key in run.keys}
    assert keys == {'space', 'ctrl+s'}
    send_group = [b for b in KEYMAP if b.group == keymap.SEND and b.show]
    assert {b.show for b in send_group} == {'space'}


def test_every_action_and_predicate_exists():
    for binding in KEYMAP:
        assert binding.mode in keymap.MODES
        for name in binding.when + binding.shown:
            assert name.lstrip('!') in PREDICATES
        for run in binding.run:
            assert run.action in ACTIONS
    used = {run.action for b in KEYMAP for run in b.run}
    assert set(ACTIONS) == used  # No orphan actions either.


def test_every_verb_a_key_runs_is_offered_by_some_entry():
    """A verb no entry kind offers (in any of its modes) could only ever say "nothing to do here"."""
    run = {run.arg for b in KEYMAP for run in b.run if run.action == 'verb'}
    run |= {'primary', 'helper', 'set_rate'}  # Run by the primary and helper actions and by :rate.
    offered = set()
    for kind, cls in KINDS.items():
        entry = cls(Tab(kind, '/x'))
        for mode in entry.modes() or ('',):
            entry.mode = mode
            offered |= set(entry.verbs())
    assert run - offered == set()


SAMPLE_STATES = [
    [], ['escape'], ['enter'], ['enter', 'enter'], INBOX, INBOX + ['enter'], INBOX + ['i'],
    ['/'], [':'], ['g'], ['?'], [':', 'l', 'o', 'g', 'enter'], ['G', 'k', 'enter'], ['G', 'k', 'enter', 'enter'],
    ['/', 'a', 'd', 'd', 'enter'], ['/', 'f', 'i', 'b', 'enter', 'l', 'enter'], ['/', 'r', 'a', 't', 'e'],
]


@pytest.mark.parametrize('keys', SAMPLE_STATES, ids=[' '.join(k) or 'start' for k in SAMPLE_STATES])
def test_no_key_has_two_meanings(keys):
    """Dispatch takes the first matching row; any other row that matches must agree with it."""
    nav = nav_after(keys, RowsWorld())
    mode = nav.input_mode()
    candidates = {key for b in KEYMAP for run in b.run for key in run.keys} - {TYPE, ANY} | {'a', 'z', 'space'}
    for key in candidates:
        actions = {(run.action, run.arg) for b in KEYMAP if b.mode == mode and keymap.holds(nav, b.when)
                   for run in b.run
                   if key in run.keys or ANY in run.keys or TYPE in run.keys and keymap.key_char(key) is not None}
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
        nav_after(INBOX + ['enter', 'j', 'j'], RowsWorld()))


def test_keys_now_in_overlays():
    assert rows(nav_after(['/'])) == [('Search', 'type', 'find by name or type'), ('Search', '↑ ↓', 'pick'),
                                      ('Search', 'enter', 'open in a tab'), ('Search', 'esc', 'close')]
    assert rows(nav_after([':'])) == [('Command', 'type', 'a command, e.g. rate 5'), ('Command', 'tab', 'complete'),
                                      ('Command', 'enter', 'run'), ('Command', 'esc', 'cancel')]
    assert [r[1] for r in rows(nav_after([':', 'l', 'o', 'g', 'enter']))] == ['j k', 'gg G', 'enter', 'esc']
    assert rows(nav_after(INBOX + ['i'], RowsWorld())) == [
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
    ('solidus', '/'), ('/', '/'), ('colon', ':'), ('question_mark', '?'), ('?', '?'),
    ('left_square_bracket', '['), ('right_square_bracket', ']'), ('full_stop', '.'),
    ('G', 'G'), ('shift+g', 'G'), ('j', 'j'), (' ', 'space'), ('space', 'space'), ('esc', 'escape'),
    ('escape', 'escape'), ('enter', 'enter'), ('tab', 'tab'), ('shift+tab', 'shift+tab'), ('ctrl+s', 'ctrl+s'),
    ('up', 'up'), ('backspace', 'backspace'), ('delete', 'delete'), ('f5', 'f5'), ('plus_sign', '+'),
])
def test_normalize_key(name, canonical):
    assert normalize_key(name) == canonical


def test_the_model_is_pure_python():
    """nav.py and keymap.py import neither textual nor rclpy (nor rich); fields.py not even rosidl."""
    code = ('import sys; tops = lambda: {m.split(".")[0] for m in sys.modules}; '
            'import ros_tui.ui.fields; fields = tops(); import ros_tui.ui.nav, ros_tui.ui.keymap; '
            'print(sorted(fields & {"rosidl_runtime_py"}), sorted(tops() & {"textual", "rclpy", "rich"}))')
    out = subprocess.run([sys.executable, '-c', code], cwd=REPO, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == '[] []'


def test_the_key_tables_in_usage_md_match_the_keymap():
    """docs/usage.md lists every listed row of KEYMAP, mode by mode, in the table's order."""
    doc = (REPO / 'docs' / 'usage.md').read_text(encoding='utf-8').split('## Every key', 1)[1]
    cells = [[cell.strip().strip('`') for cell in line.strip('|').split('|')]
             for line in doc.splitlines() if line.startswith('| `')]
    names = {'rate': 'N', 'helper': 'matching', 'jump': '0–9'}  # How the labels' {vars} read in the doc.
    modes = ('normal', 'g', 'insert', 'search', 'command', 'activity', 'helper')
    assert [(keys, label, alias) for keys, label, alias, _ in cells] == [
        (b.show.format(**names), b.label.format(**names), b.alias)
        for mode in modes for b in KEYMAP if b.mode == mode and b.show]
