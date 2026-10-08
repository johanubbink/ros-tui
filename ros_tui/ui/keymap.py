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

"""The one table of keys. Dispatch (nav.py), the footer, `?`, the `g…` popup and docs/usage.md read it.

Pure Python: no textual, no rclpy. Each `Binding` is one row of the "Keys right now" list (`?`),
with the keys it dispatches. Rows with an empty `show` only dispatch; rows without `run` are only
listed (another row does the work).

Keys are canonical names: a printable character as itself ('j', 'G', '/', '?', '['), 'space', and
textual's names for the rest ('enter', 'escape', 'tab', 'shift+tab', 'up', 'ctrl+s'). The app hands
in a symbol as its character; `normalize_key` also reads a symbol's unicode name ('question_mark',
'left_square_bracket'), as tests may write it.
"""

import unicodedata
from dataclasses import dataclass
from typing import NamedTuple

TYPE = 'type'  # Pseudo key: any printable character (space included).
ANY = '*'  # Pseudo key: any key at all.

# Input modes, in routing order: the first that applies gets the key (see NavState.input_mode).
MODES = ('whichkey', 'helper', 'command', 'activity', 'search', 'insert', 'g', 'normal')

_NAMED = frozenset({
    'enter', 'escape', 'tab', 'shift+tab', 'backspace', 'delete', 'space',
    'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown', 'insert',
})
_ALIASES = {
    'esc': 'escape', 'return': 'enter', 'ctrl+m': 'enter', 'ctrl+j': 'enter', 'ctrl+i': 'tab',
    'backtab': 'shift+tab', 'ctrl+h': 'backspace', ' ': 'space',
}
_DISPLAY = {'escape': 'esc', 'ctrl+s': '^s', 'ctrl+f': '^f'}


def normalize_key(key: str) -> str:
    """Canonical name for a textual key name or a typed character."""
    key = _ALIASES.get(key, key)
    if len(key) == 1 or key in _NAMED or '+' in key and key != '+':
        if key.startswith('shift+') and len(key) == 7 and key[6].isalpha():
            return key[6].upper()
        return key
    # A symbol by its unicode name: 'question_mark', 'full_stop', 'solidus'.
    try:
        char = unicodedata.lookup(key.replace('_', ' '))
    except KeyError:
        return key
    return char if char.isprintable() and char != ' ' else key


def key_char(key: str) -> str | None:
    """The character a canonical key types, or None for keys that don't type."""
    if key == 'space':
        return ' '
    return key if len(key) == 1 and key.isprintable() else None


def key_display(key: str) -> str:
    """How a key reads in log lines: 'esc', '^s', 'space', 'shift+tab'."""
    return _DISPLAY.get(key, key)


class Run(NamedTuple):
    keys: tuple[str, ...]
    action: str  # A NavState action (nav.ACTIONS).
    arg: object = None  # Handed to the action: a step (1 / -1), a verb's name, ...


@dataclass(frozen=True)
class Binding:
    mode: str  # One of MODES.
    group: str  # Heading in `?` and docs/usage.md.
    show: str  # The key as the lists print it; '' keeps the row out of the lists.
    label: str  # What it does; may hold {rate} or {helper} (and `show` {jump}).
    alias: str = ''  # The familiar alternative, listed as "also …".
    when: tuple[str, ...] = ()  # Context predicates (PREDICATES, '!' negates) that must all hold.
    shown: tuple[str, ...] = ()  # Extra predicates for listing the row; dispatch ignores them.
    run: tuple[Run, ...] = ()  # What its keys dispatch.


def _b(mode, group, show, label, alias='', when='', shown='', run=()):
    """Compact row constructor: predicates and keys as space-separated strings."""
    return Binding(mode, group, show, label, alias, tuple(when.split()), tuple(shown.split()),
                   tuple(Run(tuple(keys.split()), *rest) for keys, *rest in run))


def _area_id(nav):
    area = nav.area()
    return area.id if area else None


def _kind(nav):
    return nav.tab.kind if nav.tab else None


PREDICATES = {
    'tabs': lambda nav: nav.layer == 'tabs',
    'in': lambda nav: nav.layer == 'in',
    'area': lambda nav: nav.layer == 'area',
    'home': lambda nav: nav.tab is None,
    'entry': lambda nav: nav.tab is not None,
    'areas2': lambda nav: len(nav.areas()) > 1,
    'editable': lambda nav: bool(nav.area() and nav.area().editable),
    'ifs': lambda nav: _area_id(nav) == 'ifs',
    'out': lambda nav: _area_id(nav) == 'out',
    'topic': lambda nav: _kind(nav) == 'topics',
    'service': lambda nav: _kind(nav) == 'services',
    'action': lambda nav: _kind(nav) == 'actions',
    'node': lambda nav: _kind(nav) == 'nodes',
    'echo': lambda nav: nav.entry_mode() == 'echo',
    'publish': lambda nav: nav.entry_mode() == 'publish',
    'helper_here': lambda nav: nav.helper_name() is not None,
    # An area of field rows that fold (fields.py): a message being edited or a service response.
    'fields': lambda nav: bool(nav.area() and nav.area().folds),
    'enum_helper': lambda nav: getattr(nav.overlay, 'kind', None) == 'enum',  # Only a Helper has a kind.
    'rate_edit': lambda nav: nav.editing_in('rate') is not None,
    'field_edit': lambda nav: nav.editing_in('msg') is not None,
    'param_edit': lambda nav: nav.editing_in('par') is not None,
}

SEND = 'Do (only these send)'
_DIGITS = ' '.join('0123456789')

# Order matters twice: dispatch takes the first row that matches, and the lists keep this order
# (grouped by first appearance). Rows that dispatch the same key never apply
# in the same context (test_keymap checks this).
KEYMAP = (
    # ---- overlays ----
    _b('whichkey', '', '', 'close the popup', run=[(ANY, 'close_overlay')]),

    _b('helper', 'Helper', 'j k ↑ ↓', 'next option / way to enter it', when='enum_helper'),
    _b('helper', 'Helper', 'tab', 'next option / way to enter it', when='!enum_helper'),
    _b('helper', 'Helper', '{jump}', 'jump / next field', when='enum_helper'),
    _b('helper', 'Helper', '↑ ↓', 'jump / next field', when='!enum_helper'),
    _b('helper', 'Helper', 'type', 'change the value', when='!enum_helper'),
    _b('helper', 'Helper', 'enter', 'apply (u undoes)', run=[('enter', 'verb', 'helper_apply')]),
    _b('helper', 'Helper', 'esc', 'cancel, nothing changes', run=[('escape', 'close_overlay')]),
    _b('helper', '', '', 'helper keys', run=[(ANY, 'helper_key')]),

    _b('command', 'Command', 'type', 'a command, e.g. rate 5', run=[(TYPE, 'cmd_type'), ('backspace', 'cmd_back')]),
    _b('command', 'Command', 'tab', 'complete', run=[('tab shift+tab', 'cmd_complete')]),
    _b('command', 'Command', '', 'pick a suggestion', run=[('up', 'cmd_move', -1), ('down', 'cmd_move', 1)]),
    _b('command', 'Command', 'enter', 'run', run=[('enter', 'cmd_run')]),
    _b('command', 'Command', 'esc', 'cancel', run=[('escape', 'close_overlay')]),

    _b('activity', 'Activity', 'j k', 'move', '↑ ↓', run=[('j down', 'log_step', 1), ('k up', 'log_step', -1)]),
    _b('activity', 'Activity', 'gg G', 'newest / oldest', run=[('g', 'log_end', False), ('G', 'log_end', True)]),
    _b('activity', 'Activity', 'enter', "go to that entry's tab", run=[('enter', 'log_enter')]),
    _b('activity', 'Activity', 'esc', 'close', run=[('escape', 'close_overlay')]),

    _b('search', 'Search', 'type', 'find by name or type', run=[(TYPE, 'search_type'), ('backspace', 'search_back')]),
    _b('search', 'Search', '↑ ↓', 'pick', run=[('down', 'search_step', 1), ('up', 'search_step', -1)]),
    _b('search', 'Search', 'enter', 'open in a tab', run=[('enter', 'search_enter')]),
    _b('search', 'Search', 'esc', 'close', run=[('escape', 'close_overlay')]),

    _b('insert', 'Rate', 'type', 'a rate in Hz (0.1–100)', when='rate_edit'),
    _b('insert', 'Rate', 'enter / esc', 'keep it (u undoes later)', when='rate_edit'),
    _b('insert', 'Rate', '^s', 'keep it and publish once', when='rate_edit'),
    _b('insert', 'Insert', 'type', 'change the value', when='!rate_edit'),
    _b('insert', 'Insert', 'esc / enter', 'keep it, back to normal', when='!rate_edit'),
    _b('insert', 'Insert', 'tab', 'keep it, edit the next field', when='field_edit',
       run=[('tab', 'edit_step', 1), ('shift+tab', 'edit_step', -1)]),
    _b('insert', 'Insert', '^s', 'keep it and set it', when='param_edit'),
    _b('insert', 'Insert', '^s', 'keep it and send', when='!rate_edit !param_edit'),
    _b('insert', '', '', 'insert keys', run=[
        ('escape enter', 'edit_keep'), ('ctrl+s', 'primary'), ('backspace', 'edit_back'), (TYPE, 'edit_type')]),

    _b('g', 'Go', 'gg', 'to the top', run=[('g', 'move_end', False)]),
    _b('g', 'Go', 'gt', 'next tab', run=[('t', 'step_tab', 1)]),
    _b('g', 'Go', 'gT', 'previous tab', run=[('T', 'step_tab', -1)]),
    _b('g', '', '', 'cancel the prefix', run=[('escape', 'g_cancel')]),

    # ---- normal mode ----
    _b('normal', 'Layers', 'enter', 'down one layer / do it', run=[('enter', 'go_down')]),
    _b('normal', 'Layers', 'esc', 'up one layer', run=[('escape', 'go_up')]),

    _b('normal', 'Move', 'h l', 'previous / next tab', '← → tab', when='tabs',
       run=[('l right tab', 'step_tab_cursor', 1), ('h left shift+tab', 'step_tab_cursor', -1)]),

    _b('normal', 'Move', 'j k', 'pick an entry', '↑ ↓', when='in home',
       run=[('j down', 'step_list', 1), ('k up', 'step_list', -1)]),
    _b('normal', 'Move', 'gg G', 'top / bottom', when='in home'),
    _b('normal', 'Move', 'tab', 'filter by kind', when='in home',
       run=[('tab', 'step_chip', 1), ('shift+tab', 'step_chip', -1)]),

    _b('normal', 'Move', 'h j k l', 'pick an area', 'arrows tab', when='in entry', shown='areas2',
       run=[('l j right down tab', 'step_area', 1), ('h k left up shift+tab', 'step_area', -1)]),
    _b('normal', 'Edit', 'i', 'edit the field under the cursor', 'enter enter', when='in entry editable',
       run=[('i a', 'edit')]),
    _b('normal', 'Edit', 'c', 'clear it and edit', when='in entry editable', run=[('c', 'edit', True)]),

    _b('normal', 'Move', 'j k', 'pick a field or row', '↑ ↓', when='area',
       run=[('j down tab', 'step_row', 1), ('k up shift+tab', 'step_row', -1)]),
    _b('normal', 'Move', 'gg G', 'first / last', when='area'),
    _b('normal', 'Move', 'h l', 'fold / unfold (h on a field: up to its parent)', '← →', when='area fields',
       run=[('h left', 'verb', 'fold'), ('l right', 'verb', 'unfold')]),
    _b('normal', 'Edit', 'i  enter', 'edit the value', when='area', shown='editable', run=[('i a', 'edit')]),
    _b('normal', 'Edit', 'c', 'clear it and edit', when='area', shown='editable', run=[('c', 'edit', True)]),
    _b('normal', 'Edit', 'enter', 'unfold / fold a nested message or list', when='area fields'),
    _b('normal', 'Edit', 'o', 'add a list element after this one', when='area fields editable',
       run=[('o', 'verb', 'add_item')]),
    _b('normal', 'Edit', 'd', 'delete this list element (u undoes)', when='area fields editable',
       run=[('d', 'verb', 'delete_item')]),
    _b('normal', 'Edit', 'enter', 'open it in a tab', when='area ifs'),
    _b('normal', 'Edit', 'enter', 'show / hide the field', when='area out topic'),
    _b('normal', 'Edit', 'f', 'fill it with the {helper} helper', when='area helper_here'),

    _b('normal', 'Go', '/', 'search everything', '^f', run=[('/ ctrl+f', 'search_open')]),
    _b('normal', 'Go', ':log', 'all activity'),
    _b('normal', 'Go', ':', 'command line', run=[(':', 'cmd_open')]),
    _b('normal', 'Go', '0 1…9', '☰ list / tab N', run=[(_DIGITS, 'goto_tab')]),
    _b('normal', 'Go', 'H L', 'previous / next tab', 'gT gt', run=[('H', 'step_tab', -1), ('L', 'step_tab', 1)]),
    _b('normal', 'Go', 'x', 'close the tab', run=[('x', 'close')]),
    _b('normal', 'Go', 'u', 'undo in this tab (or reopen a closed tab)', run=[('u', 'undo')]),
    _b('normal', 'Go', '', 'prefix, bottom, copy, paste',
       run=[('g', 'g_prefix'), ('G', 'move_end', True), ('y', 'verb', 'yank'), ('p', 'verb', 'paste')]),

    # Entry verbs: layers 2 and 3 of an entry. Only space / ^s sends what's in the editor, and r
    # starts a repeating publish; s only ever stops or cancels.
    _b('normal', SEND, 'space', 'start / stop echo', '^s', when='entry !tabs topic echo'),
    _b('normal', SEND, 'space', 'publish once', '^s', when='entry !tabs topic publish'),
    _b('normal', SEND, 'space', 'call', '^s', when='entry !tabs service'),
    _b('normal', SEND, 'space', 'send goal', '^s', when='entry !tabs action'),
    _b('normal', SEND, 'space', 'set changed parameters', '^s', when='entry !tabs node'),
    _b('normal', 'Do', 'r', 'repeat at {rate} Hz', when='entry !tabs topic publish'),
    _b('normal', 'Do', 'R', 'change the repeat rate', ':rate 5', when='entry !tabs topic publish'),
    _b('normal', 'Do', 's', 'stop repeating', when='entry !tabs topic publish'),
    _b('normal', 'Do', 'e', 'echo ⇄ publish', when='entry !tabs topic'),
    _b('normal', 'Inspect', 'enter', 'into the latest message: values freeze', when='in topic echo'),
    _b('normal', 'Inspect', 'esc', 'out again: values go live', when='area topic echo'),
    _b('normal', 'Do', 's', 'cancel goal', when='entry !tabs action'),
    _b('normal', 'Do', 'y  p', 'copy / paste a message', when='entry !tabs !node'),
    _b('normal', 'Do', '[ ]', 'older / newer sends', when='entry !tabs !node !echo'),
    _b('normal', 'Do', 'u', 'undo a parameter change', when='entry !tabs node'),
    # The verbs dispatch on every entry; the entry says when one doesn't apply to it.
    _b('normal', SEND, '', 'entry verbs', when='entry !tabs', run=[
        ('space ctrl+s', 'primary'), ('s', 'verb', 'secondary'), ('r', 'verb', 'repeat'), ('R', 'verb', 'rate'),
        ('e', 'switch_mode'), ('f', 'helper'), ('[', 'verb', 'history_older'), (']', 'verb', 'history_newer')]),

    _b('normal', 'Help', '?', 'all keys right now', run=[('?', 'which_key')]),
)


class KeyRow(NamedTuple):
    """One line of the "Keys right now" list: its group, key, what it does and the familiar alias."""

    group: str
    keys: str
    label: str
    alias: str


def holds(nav, predicates) -> bool:
    for name in predicates:
        negate = name.startswith('!')
        if PREDICATES[name.lstrip('!')](nav) == negate:
            return False
    return True


def lookup(nav, mode: str, key: str) -> Run | None:
    """What `key` runs in `mode` right now, or None."""
    typed = key_char(key) is not None
    for binding in KEYMAP:
        if binding.mode != mode or not binding.run or not holds(nav, binding.when):
            continue
        for run in binding.run:
            if key in run.keys or ANY in run.keys or typed and TYPE in run.keys:
                return run
    return None


def rows_for(nav, mode: str) -> list[KeyRow]:
    """The listed rows of one mode that apply now, grouped by first appearance."""
    values = nav.label_vars()
    rows = [KeyRow(b.group, b.show.format(**values), b.label.format(**values), b.alias) for b in KEYMAP
            if b.mode == mode and b.show and holds(nav, b.when) and holds(nav, b.shown)]
    groups = list(dict.fromkeys(row.group for row in rows))
    return [row for group in groups for row in rows if row.group == group]


def keys_now(nav) -> list[KeyRow]:
    """What the keys do on the current layer or overlay."""
    return rows_for(nav, nav.list_mode())


def which_key_items(nav) -> list[KeyRow]:
    """The `?` popup lists keys_now(); the `g` popup lists what can follow the prefix."""
    return rows_for(nav, 'g') if nav.input_mode() == 'g' else keys_now(nav)
