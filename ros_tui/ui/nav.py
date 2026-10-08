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

"""The navigation model of the UI: tabs, layers, cursors, the overlay and the `g` prefix.

Pure Python (no textual, no rclpy). Widgets render a `NavState` and hand it every key through
`handle_key` and every click through `click`; `keymap.KEYMAP` says which action a key runs. What an
entry holds (its areas, rows, values and verbs) comes from its `Entry` (entries/base.py), one per
tab, made by `new_entry`, so the topic, service, action and node entries plug in without the model
knowing about them. What there is to open is the `Catalog` (catalog.py), what the UI says back is
the `Feedback` (feedback.py), and the `:` line is a `CommandLine` (command_line.py).

The layers, top to bottom: TABS (the tab row) › IN (inside a tab: the ☰ list, or an entry's area
pick) › AREA (the rows of one area) › EDIT (insert: typing into one value). esc goes up one, enter
goes down one. At most one overlay sits on top and has the keys: search, the command line, :log,
a field helper, or the which-key popup (`?`, or the `g` prefix waiting for its next key).
"""

from dataclasses import dataclass, field
from typing import Any, Callable, NamedTuple

from ros_tui.ui import keymap
from ros_tui.ui.catalog import KINDS, Catalog
from ros_tui.ui.command_line import CommandLine
from ros_tui.ui.entries.base import Area, Editing, Entry, Running, Tab, UndoEntry
from ros_tui.ui.feedback import Feedback
from ros_tui.ui.helpers import Helper
from ros_tui.ui.keymap import key_char, key_display, normalize_key
from ros_tui.ui.register import Register

TABS, IN, AREA, EDIT = ('tabs', 'in', 'area', 'edit')
NOTHING_TO_UNDO = 'nothing to undo here'


@dataclass
class Search:
    q: str = ''
    cur: int = 0

    def edit(self, text: str) -> None:
        self.q = text
        self.cur = 0


@dataclass
class LogView:
    cur: int = 0


@dataclass(frozen=True)
class WhichKey:
    what: str  # 'all' (the ? popup) or 'g' (the prefix waiting for its next key).


Overlay = Search | CommandLine | LogView | Helper | WhichKey

# The keymap mode of each overlay that takes the keys as a list (which-key sits on top of the mode below).
OVERLAY_MODES = {Helper: 'helper', CommandLine: 'command', LogView: 'activity', Search: 'search'}


class Footer(NamedTuple):
    mode: str  # normal, insert, helper, search or command.
    path: tuple[str, ...]  # The breadcrumb; the last part is where you are.
    esc: str  # What esc does here ('' when nothing, or hidden by search / which-key).
    enter: str
    pending: str  # A pending prefix ('g'), shown as "g…".
    helper: str  # 'Quaternion' when the row under the cursor has a helper, else ''.


class Press(NamedTuple):
    key: str  # Canonical (keymap.normalize_key).
    char: str | None  # What it types, if anything.
    how: str  # How it reads in the log: 'esc', '^s', 'j'.
    arg: Any = None  # The argument its keymap row gives the action (keymap.Run.arg).


@dataclass
class NavState:
    new_entry: Callable[[Tab], Entry] = Entry  # Makes a tab's entry; the app's is entries.kinds.entry_factory.
    feedback: Feedback = field(default_factory=Feedback)  # The log, toast, errlines, activity and send flash.
    catalog: Catalog = field(default_factory=Catalog)
    tabs: list[Tab] = field(default_factory=list)
    active: int = -1  # -1 is the ☰ list (tab 0).
    layer: str = IN
    tab_cur: int = -1  # The cursor on the tab row (layer TABS).
    chip: int = -1  # The kind filter on the ☰ list: -1 all, else an index into KINDS.
    list_cur: int = 0
    entries: dict[Tab, Entry] = field(default_factory=dict)  # Every entry opened so far, its tab open or not.
    editing: Editing | None = None
    overlay: Overlay | None = None  # What sits on top and has the keys.
    undo_stack: list[UndoEntry] = field(default_factory=list)
    register: Register | None = None  # What y copied, for p (one, app-wide).
    quit: bool = False  # :q asked to leave; the app acts on it.
    _area_idx: dict[tuple[Tab, str], int] = field(default_factory=dict)  # (tab, its entry's mode) -> area.
    _row_idx: dict[tuple[Tab, str], int] = field(default_factory=dict)  # (tab, area id) -> row.

    # ---------- driving it ----------
    def handle_key(self, key: str) -> bool:
        """Route one key (a textual key name or a character). False when nothing wanted it."""
        key = normalize_key(key)
        mode = self.input_mode()
        how = key_display(key)
        if mode == 'g':  # The key after g resolves the prefix, whatever it is.
            self.overlay = None
            how = 'g' + how
        run = keymap.lookup(self, mode, key)
        if run:
            ACTIONS[run.action](self, Press(key, key_char(key), how, run.arg))
            return True
        if mode == 'g':
            self.feedback.log_line(how, 'no such key')
            return True
        if mode != 'normal':
            return True  # Overlays and insert are modal: they swallow what they don't use.
        if key_char(key) is None:
            return False
        if self.layer != TABS:
            self.feedback.hint(how)
        return True

    def click(self, target: tuple[str, Any] | None, on_popup: bool = False) -> None:
        """A click on what a view tagged with `target`, (what, arg) as in `CLICKS` (None where a
        click does nothing). It does what the keys would, and the log reads "click".

        An overlay (search, :log, the command line, the helper, which-key, the g popup) takes only
        clicks on itself (`on_popup`); a click anywhere else closes it as esc does, and does nothing
        else. A click while typing a value keeps it first, as esc does, except on the primary
        button: that sends, as ^s does in insert."""
        if self.overlay is not None and not on_popup:
            self._close_overlay('click')
            return
        if target is None:
            return
        what, arg = target
        if self.layer == EDIT and target != ('verb', 'primary'):
            self._commit_edit('esc')
        CLICKS[what](self, arg)

    def tick(self) -> str:
        """Let the entries take in what arrived (echoes), and expire what is timed (Feedback.tick).
        What changed, so the views redraw: 'all', 'entries' (only what the entries show: an echo's
        values, a goal's spinner; no view moves or changes size) or '' (nothing)."""
        changed = any([entry.tick(self) for entry in self.entries.values()])  # A list: every entry ticks.
        return 'all' if self.feedback.tick() else 'entries' if changed else ''

    def set_catalog(self, graph: Any) -> None:
        """Feed the ☰ list from a GraphSnapshot (see Catalog.set)."""
        self.catalog.set(graph)
        self.list_cur = _clamp(self.list_cur, len(self.catalog.rows(self.chip)) - 1)

    # ---------- where we are ----------
    @property
    def tab(self) -> Tab | None:
        return self.tabs[self.active] if 0 <= self.active < len(self.tabs) else None

    def shown(self, kind: type) -> Any:
        """The overlay if it is a `kind` (Search, CommandLine, LogView, Helper, WhichKey), else None."""
        return self.overlay if isinstance(self.overlay, kind) else None

    def entry(self, tab: Tab) -> Entry:
        """The entry of `tab`: made the first time it is asked for, then kept, also after its tab
        closes (its edits, history and echo are there when it opens again)."""
        entry = self.entries.get(tab)
        if entry is None:
            entry = self.entries[tab] = self.new_entry(tab)
        return entry

    def entry_mode(self) -> str | None:
        return self.entry(self.tab).mode or None if self.tab else None

    def is_open(self, kind: str, name: str) -> bool:
        return Tab(kind, name) in self.tabs

    def areas(self) -> tuple[Area, ...]:
        return self.entry(self.tab).areas() if self.tab else ()

    def area_index(self) -> int:
        areas = self.areas()
        if not areas:
            return 0
        return min(self._area_idx.get((self.tab, self.entry(self.tab).mode), 0), len(areas) - 1)

    def area(self) -> Area | None:
        areas = self.areas()
        return areas[self.area_index()] if areas else None

    def row_count(self, area: Area | None = None) -> int:
        area = area or self.area()
        return self.entry(self.tab).row_count(area) if self.tab and area else 0

    def row_index(self, area: Area | None = None) -> int:
        """The current row of the area, kept within its rows (they can change when the bridge answers)."""
        area = area or self.area()
        if not self.tab or not area:
            return 0
        return _clamp(self._row_idx.get((self.tab, area.id), 0), self.row_count(area) - 1)

    def running(self, kind: str, name: str) -> tuple[Running, ...]:
        """What the entry has running (◉ echoing, ↻ 10 Hz), for its tab, list row and search row."""
        entry = self.entries.get(Tab(kind, name))
        return entry.running() if entry else ()

    def running_all(self) -> list[tuple[Tab, Running]]:
        """Everything running, for the top bar, in KINDS order."""
        tabs = sorted(self.entries, key=lambda tab: KINDS.index(tab.kind) if tab.kind in KINDS else len(KINDS))
        return [(tab, marker) for tab in tabs for marker in self.entries[tab].running()]

    def editing_in(self, area_id: str) -> Editing | None:
        """The value being typed in the area (or editor) `area_id`, or None."""
        editing = self.editing
        return editing if self.layer == EDIT and editing is not None and editing.area == area_id else None

    def helper_name(self) -> str | None:
        """The helper of the field under the cursor (areas with helpers only)."""
        area = self.area()
        if self.layer == TABS or area is None or not area.helpers:
            return None
        return self.entry(self.tab).helper_name(area, self.row_index(area))

    def label_vars(self) -> dict[str, Any]:
        helper = self.shown(Helper)
        return {'rate': '', 'helper': self.helper_name() or '', 'jump': helper.jump_keys() if helper else '',
                **(self.entry(self.tab).label_vars() if self.tab else {})}

    def list_mode(self) -> str:
        """The keymap mode whose keys "Keys right now" lists: the overlay's, insert or normal."""
        return OVERLAY_MODES.get(type(self.overlay)) or ('insert' if self.layer == EDIT else 'normal')

    def input_mode(self) -> str:
        """The keymap mode that gets the next key: the which-key popups (? and g…) sit on top of list_mode."""
        which = self.shown(WhichKey)
        if which:
            return 'g' if which.what == 'g' else 'whichkey'
        return self.list_mode()

    # ---------- the footer ----------
    def footer(self) -> Footer:
        which = self.shown(WhichKey)
        hide = self.shown(Search) is not None or which == WhichKey('all')
        helper = None
        if not (hide or self.shown(Helper) or self.shown(LogView) or self.layer == EDIT):
            helper = self.helper_name()
        mode = self.list_mode()
        return Footer('normal' if mode == 'activity' else mode,  # The :log view keeps NORMAL.
                      self._path(), '' if hide else self._esc_label(), '' if hide else self._enter_label(),
                      'g' if which == WhichKey('g') else '', helper or '')

    def summary(self) -> dict[str, Any]:
        """Plain data for the harness's state JSON and for tests."""
        foot = self.footer()
        search, cmd, which, log = self.shown(Search), self.shown(CommandLine), self.shown(WhichKey), self.feedback.log
        toast = self.feedback.toast
        return {
            'layer': self.layer, 'mode': foot.mode, 'path': list(foot.path), 'esc': foot.esc,
            'enter': foot.enter, 'pending': foot.pending, 'active': self.active, 'tab_cur': self.tab_cur,
            'tabs': [tab.name for tab in self.tabs], 'entry_mode': self.entry_mode(), 'chip': self.chip,
            'list_cur': self.list_cur,
            'area': self.area().id if self.tab and self.area() else None,
            'row': self.row_index() if self.tab else None,
            'overlay': type(self.overlay).__name__ if self.overlay else None,
            'overlay_cur': getattr(self.overlay, 'cur', None),  # The picked row of search, :, :log.
            'search': search.q if search else None, 'cmd': cmd.q if cmd else None,
            'which_key': which.what if which else None, 'log': log[0] if log else None,
            'toast': [toast.text, toast.kind] if toast else None,
            'register': f'{self.register.label} from {self.register.source}' if self.register else None,
        }

    def _path(self) -> tuple[str, ...]:
        parts = ['tabs']
        if self.layer == TABS:
            return tuple(parts)
        parts.append(self.tab.name if self.tab else '☰ list')
        if self.layer == IN or not self.tab:
            return tuple(parts)
        if self.layer == EDIT and self.editing and self.editing.crumb:
            return tuple(parts) + self.editing.crumb + ('editing',)
        area = self.area()
        parts.append(area.title.lower() if area else '')
        if self.layer == AREA:
            return tuple(parts)
        return tuple(parts) + ('editing',)

    def _esc_label(self) -> str:
        if self.shown(Helper):
            return 'cancel'
        if self.shown(LogView):
            return 'close'
        if self.layer == AREA and self.tab:
            label = self.entry(self.tab).esc_label(self.area())
            return label or ('pick another area' if len(self.areas()) > 1 else 'back out')
        return {EDIT: 'keep it', IN: 'tab row', TABS: ''}[self.layer]

    def _enter_label(self) -> str:
        if self.shown(Helper):
            return 'apply'
        if self.shown(LogView):
            return 'go there'
        if self.layer == TABS:
            return 'go in'
        if self.layer == IN:
            if not self.tab:
                rows = self.catalog.rows(self.chip)
                return f'open {rows[self.list_cur][1].name}' if 0 <= self.list_cur < len(rows) else ''
            area = self.area()
            return f'into {area.title.lower()}' if area else ''
        if self.layer == AREA:
            area = self.area()
            if area is None:
                return ''
            return self.entry(self.tab).enter_label(area, self.row_index(area)) or area.enter
        return 'keep it'

    # ---------- what entries call ----------
    def set_row(self, index: int, area: Area | None = None) -> None:
        area = area or self.area()
        self._row_idx[(self.tab, area.id)] = index

    def open_entity(self, kind: str, name: str, how: str) -> None:
        """Open (or go to) the tab of `name`, inside it at its area pick."""
        tab = Tab(kind, name)
        is_new = tab not in self.tabs
        if is_new:
            self.tabs.append(tab)
        index = self.tabs.index(tab)
        self.entry(tab).on_open(self)
        if self.shown(Search):
            self.overlay = None
        self.active = index
        self.layer = IN
        self.editing = None
        self.feedback.log_line(how, f'{"opened" if is_new else "went to"} {name} (tab {index + 1})')

    def start_edit(self, how: str, clear: bool = False) -> bool:
        """Edit the row under the cursor (the AREA layer). False when the row isn't editable."""
        area = self.area()
        if self.tab is None or area is None:
            return False
        editing = self.entry(self.tab).start_edit(area, self.row_index(area), clear)
        if editing is None:
            return False
        self.begin_edit(editing)
        self.feedback.log_line(how, f'{"clear and edit" if clear else "edit"} {editing.field} {editing.note}')
        return True

    def begin_edit(self, editing: Editing) -> None:
        """Go into insert, typing `editing` (an entry's own editor, such as the repeat rate, starts it
        this way too); keeping it returns to `editing.back`, by default the layer it starts on."""
        if editing.back is None:
            editing.back = self.layer
        self.editing = editing
        self.layer = EDIT

    def push_undo(self, entry: UndoEntry) -> None:
        self.undo_stack.append(entry)

    def drop_undo(self, gone: Callable[[UndoEntry], bool]) -> None:
        """Forget the undo steps `gone` picks (a change that can't be undone any more)."""
        self.undo_stack[:] = [entry for entry in self.undo_stack if not gone(entry)]

    # ---------- tabs ----------
    def _activate(self, index: int, how: str, quiet: bool = False) -> None:
        self.active = index
        self.layer = IN
        self.editing = None
        if not quiet:
            self.feedback.log_line(how, '☰ the list' if index < 0 else f'tab {index + 1}: {self.tabs[index].name}')

    def _close_tab(self, index: int, how: str) -> None:
        if index < 0:
            self.feedback.log_line(how, 'the ☰ list always stays')
            return
        tab = self.tabs.pop(index)
        stopped = self.entry(tab).on_close(self)
        self.push_undo(UndoEntry(None, lambda nav: self._reopen(tab, index)))
        if self.active == index:
            self.active = min(index, len(self.tabs) - 1)
        elif self.active > index:
            self.active -= 1
        if self.layer == TABS:
            self.tab_cur = min(index, len(self.tabs) - 1)
        else:
            self.layer = IN
        self.editing = None
        self.feedback.log_line(how, f'closed {tab.name} — {" · ".join(stopped + ["u reopens it"])}')
        self.feedback.show_toast(f'closed {tab.name} · u undoes', 'info')

    def _goto_tab(self, digit: str) -> None:
        if digit == '0':
            self._activate(-1, digit)
        elif int(digit) <= len(self.tabs):
            self._activate(int(digit) - 1, digit)
        else:
            self.feedback.log_line(digit, f'no tab {digit}')

    def _undo(self, how: str) -> None:
        """Undo your last change in this entry, or reopen the tab you just closed: a closed tab has
        no tab of its own to undo from, so any tab can reopen it."""
        index = next((i for i in range(len(self.undo_stack) - 1, -1, -1)
                      if self.undo_stack[i].owner in (None, self.tab)), -1)
        if index < 0:
            self.feedback.log_line(how, NOTHING_TO_UNDO)
            self.feedback.show_toast(NOTHING_TO_UNDO, 'info')
            return
        self.feedback.log_line(how, self.undo_stack.pop(index).revert(self))

    def _reopen(self, tab: Tab, at: int) -> str:
        """Undo closing `tab` (it was tab `at`): back in its place, or gone to if it is open again."""
        if tab in self.tabs:
            self.active = self.tabs.index(tab)
        else:
            at = min(at, len(self.tabs))
            self.tabs.insert(at, tab)
            self.active = at
        self.layer = IN
        return f'reopened {tab.name}'

    # ---------- layers ----------
    def _go_up(self, how: str) -> None:
        if self.layer == EDIT:
            self._commit_edit(how)
        elif self.layer == AREA:
            self.layer = IN
            self.feedback.log_line(how, self.entry(self.tab).leave_area(self.area()) or 'up one layer')
        elif self.layer == IN:
            self.layer = TABS
            self.tab_cur = self.active
            self.feedback.log_line(how, 'up to the tab row')
        else:
            self.feedback.log_line(how, 'top layer — :q quits')

    def _go_down(self, how: str) -> None:
        if self.layer == TABS:
            self._activate(self.tab_cur, how)
        elif self.layer == IN:
            if not self.tab:
                rows = self.catalog.rows(self.chip)
                if 0 <= self.list_cur < len(rows):
                    self.open_entity(rows[self.list_cur][0], rows[self.list_cur][1].name, how)
                return
            area = self.area()
            if area is None:
                self.feedback.log_line(how, 'nothing inside this tab yet')
                return
            self.layer = AREA
            self.feedback.log_line(how, f'inside {area.title.lower()}')
        elif self.layer == AREA:
            # enter on a row: the entry's own action first (fold a list, open an interface), else edit it.
            if not self.entry(self.tab).activate_row(self, self.area(), self.row_index(), how) \
                    and not self.start_edit(how):
                self.feedback.log_line(how, 'nothing to edit here — esc goes back up')
        else:
            self._commit_edit(how)

    def _enter_area(self, index: int, how: str) -> None:
        """Go inside the entry's area at `index` (a click on its panel)."""
        if self.tab is None or not 0 <= index < len(self.areas()):
            return
        self._area_idx[(self.tab, self.entry(self.tab).mode)] = index
        self.layer = AREA
        self.feedback.log_line(how, f'inside {self.area().title.lower()}')

    # ---------- insert ----------
    def _commit_edit(self, how: str) -> bool:
        """Keep the typed value. On a bad value, esc drops it (keeping the old one) and anything else
        stays in insert with an error line. True when the edit ended."""
        editing = self.editing
        if editing is None:
            return True
        result = self.entry(self.tab).commit_edit(editing)
        if not result.ok:
            return self._bad_value(how, result.text)
        if result.undo:
            self.push_undo(result.undo)
        if result.activity:
            self.feedback.add_activity(self.tab, *result.activity)
        self.feedback.clear_error(self.tab)
        self.feedback.log_line(how, result.text)
        self.editing = None
        self.layer = editing.back
        return True

    def _bad_value(self, how: str, message: str) -> bool:
        if how == 'esc':
            self.feedback.refuse(how, f'{message} — kept the old value', f'✗ {message} — dropped, kept the old value')
            self.feedback.clear_error(self.tab)
            self.layer = self.editing.back
            self.editing = None
            return True
        self.feedback.log_line(how, f'✗ {message} — still editing (esc drops it)')
        self.feedback.report_error(self.tab, message)
        return False

    def _edit_step(self, how: str, delta: int) -> None:
        """tab / shift+tab in insert: keep the value and edit the next / previous field, skipping
        rows that aren't edited (a folded message). Past the last one it edits the same field again."""
        row = self.editing.row
        if not self._commit_edit(how):
            return
        last = self.row_count() - 1
        for index in range(row + delta, last + 1 if delta > 0 else -1, delta):
            self.set_row(index)
            if self.start_edit(how):
                return
        self.set_row(_clamp(row, last))
        self.start_edit(how)

    def _type_char(self, char: str) -> None:
        if self.editing.fresh:
            self.editing.value = ''
            self.editing.fresh = False
        self.editing.value += char

    def _backspace(self) -> None:
        self.editing.value = '' if self.editing.fresh else self.editing.value[:-1]
        self.editing.fresh = False

    def _edit_row(self, how: str, clear: bool = False) -> None:
        """i / a / c: edit the row under the cursor. From the area pick (IN) they go into the area first."""
        back = self.layer
        self.layer = AREA
        if not self.start_edit(how, clear):
            self.layer = back
            self.feedback.hint(how)

    # ---------- verbs ----------
    def _verb(self, name: str, how: str, arg: Any = None) -> None:
        """Run the entry's verb `name`; where it has none (or on the ☰ list), say it isn't here."""
        entry = self.entry(self.tab) if self.tab else None
        run = entry.verbs().get(name) if entry else None
        if run is not None:
            run(self, how, arg)
            return
        if entry is None and name in ('yank', 'paste'):
            self.feedback.log_line(how, 'open an entry first')
            return
        log, toast = NOT_HERE.get(name, ('nothing to do here', ''))
        self.feedback.log_line(how, log)
        if toast:
            self.feedback.show_toast(toast, 'bad')

    def _primary(self, how: str) -> None:
        """space / ^s: the entry's one sending verb. In insert it keeps the value first."""
        if self.tab is None:
            return
        if self.layer == EDIT and not self._commit_edit(how):
            return
        self._verb('primary', how)

    def _open_helper(self, how: str) -> None:
        """f: the entry opens the helper of the field under the cursor (from the area pick it goes
        into the area first)."""
        area = self.area()
        if self.layer == IN and area and area.helpers:
            self.layer = AREA
        if self.helper_name() is None:
            self.feedback.refuse(how, 'no helper for this field — fields with one show [f …]', 'no helper on this field')
            return
        self._verb('helper', how)

    def _switch_mode(self, how: str, to: str | None = None) -> None:
        """e, :echo, :pub, a click on the switch: switch the entry to mode `to`, or its next one (a
        topic's Echo / Publish). What is being typed is kept first; the cursor goes back to the area pick."""
        modes = self.entry(self.tab).modes() if self.tab else ()
        if not modes:
            self.feedback.log_line(how, 'only topics have Echo / Publish')
            return
        if self.layer == EDIT:
            self._commit_edit(how)
        entry = self.entry(self.tab)
        entry.mode = to or modes[(modes.index(entry.mode) + 1) % len(modes) if entry.mode in modes else 0]
        self.layer = IN
        self.feedback.log_line(how, f'now in {entry.mode}')

    # ---------- moving ----------
    def _move_end(self, how: str, bottom: bool) -> None:
        """gg / G: the first / last list row, area row or tab."""
        if self.layer == IN and not self.tab:
            self.list_cur = max(0, len(self.catalog.rows(self.chip)) - 1) if bottom else 0
        elif self.layer == AREA:
            self.set_row(max(0, self.row_count() - 1) if bottom else 0)
        elif self.layer == TABS:
            self.tab_cur = len(self.tabs) - 1 if bottom else -1
        self.feedback.log_line(how, 'to the bottom' if bottom else 'to the top')

    def _set_chip(self, chip: int, how: str) -> None:
        """Filter the ☰ list by a kind chip (-1 all), the cursor on its first row."""
        self.chip = chip
        self.list_cur = 0
        self.feedback.log_line(how, f'showing {"everything" if self.chip < 0 else KINDS[self.chip]}')

    def _step_area(self, delta: int) -> None:
        count = len(self.areas())
        if count:
            self._area_idx[(self.tab, self.entry(self.tab).mode)] = (self.area_index() + delta) % count

    def _step_row(self, delta: int) -> None:
        count = self.row_count()
        if count:
            self.set_row(_clamp(self.row_index() + delta, count - 1))

    # ---------- overlays ----------
    def _close_overlay(self, how: str) -> None:
        """Close the overlay, as esc does there (a click outside it reads `how`)."""
        overlay, self.overlay = self.overlay, None
        if overlay == WhichKey('g'):
            self.feedback.log_line(how, 'g canceled')
        elif isinstance(overlay, Helper):
            self.feedback.log_line('esc', 'helper closed, nothing changed')
        elif isinstance(overlay, Search):
            self.feedback.log_line('esc', 'search closed — back where you were')

    def _open(self, overlay: Overlay, how: str = '', what: str = '') -> None:
        self.overlay = overlay
        if what:
            self.feedback.log_line(how, what)

    def _search_step(self, delta: int) -> None:
        search = self.overlay
        search.cur = _clamp(search.cur + delta, len(self.catalog.search(search.q)) - 1)

    def _search_enter(self, how: str) -> None:
        rows = self.catalog.search(self.overlay.q)
        if 0 <= self.overlay.cur < len(rows):
            kind, item = rows[self.overlay.cur]
            self.open_entity(kind, item.name, how)

    def _cmd_backspace(self) -> None:
        """Backspace on an empty command line closes it."""
        if self.overlay.q:
            self.overlay.edit(self.overlay.q[:-1])
        else:
            self.overlay = None

    def _cmd_enter(self) -> None:
        """enter runs the picked command (CommandLine.picked). One that takes an argument stays open for it."""
        text = self.overlay.picked()
        self.overlay = None
        if text.endswith(' '):
            self.overlay = CommandLine(text)
        elif text.strip():
            name, *rest = text.split()
            run = COMMANDS.get(name)
            if run is None:
                self.feedback.refuse(':' + name, f'unknown command :{name} — : then tab lists them', 'unknown command')
            else:
                run(self, name, ' '.join(rest))

    def _list_kind(self, name: str) -> None:
        """:topics … :nodes, :all: the ☰ list, showing only that kind (or everything)."""
        self.chip = KINDS.index(name) if name in KINDS else -1
        self.list_cur = 0
        self._activate(-1, '', quiet=True)
        self.feedback.log_line(':' + name, f'☰ lists {"everything" if name == "all" else name}')

    def _log_goto(self, index: int) -> None:
        self.overlay.cur = _clamp(index, len(self.feedback.activity) - 1)

    def _log_enter(self) -> None:
        activity, cur = self.feedback.activity, self.overlay.cur
        line = activity[cur] if cur < len(activity) else None
        self.overlay = None
        if line and line.kind:
            self.open_entity(line.kind, line.name, 'enter')

    def _click_open(self, kind: str, name: str) -> None:
        """A click on a list row, a search match or an activity line: open its entry."""
        if self.shown(LogView):
            self.overlay = None
        self.open_entity(kind, name, 'click')


def _clamp(index: int, last: int) -> int:
    """`index` kept in 0..last (0 when there is nothing)."""
    return max(0, min(last, index))


def _cycle(index: int, delta: int, count: int) -> int:
    """Step an index in -1..count-1 (-1 being ☰ or "all"), wrapping at both ends."""
    return (index + 1 + delta) % (count + 1) - 1


# What a verb says where the entry doesn't offer it (and on the ☰ list): (the log line, a red toast or '').
NOT_HERE = {
    'repeat': ('repeating is for topics', ''),
    'rate': ('repeating is for topics', ''),
    'set_rate': ('repeating is for topics', ':rate works in a topic tab'),
}


def _quit(nav: NavState) -> None:
    nav.quit = True
    nav.feedback.log_line(':q', 'quit')


# The `:` commands (command_line.COMMANDS lists them): name -> what it does, given (nav, name, argument).
COMMANDS: dict[str, Callable[[NavState, str, str], None]] = {
    **dict.fromkeys((*KINDS, 'all'), lambda nav, name, arg: nav._list_kind(name)),
    'rate': lambda nav, name, arg: nav._verb('set_rate', ':rate', arg),
    'echo': lambda nav, name, arg: nav._switch_mode(':echo', 'echo'),
    'pub': lambda nav, name, arg: nav._switch_mode(':pub', 'publish'),
    'close': lambda nav, name, arg: nav._close_tab(nav.active, ':close'),
    'help': lambda nav, name, arg: nav._open(WhichKey('all'), ':help', 'showing the keys'),
    **dict.fromkeys(('log', 'messages'), lambda nav, name, arg: nav._open(LogView(), ':log', 'all activity')),
    **dict.fromkeys(('q', 'quit'), lambda nav, name, arg: _quit(nav)),
}

# What a click does, by the `what` of its target (NavState.click); the views tag what they draw
# with a target through widgets.base.clickable.
CLICKS: dict[str, Callable[[NavState, Any], None]] = {
    'tab': lambda nav, index: nav._activate(index, 'click'),  # a tab, ☰ (-1) included
    'close': lambda nav, index: nav._close_tab(index, 'click'),  # a tab's ×
    'chip': lambda nav, chip: nav._set_chip(chip, 'click'),  # a kind chip on the ☰ list
    'open': lambda nav, entry: nav._click_open(*entry),  # (kind, name): a row, a match, an activity line
    'area': lambda nav, index: nav._enter_area(index, 'click'),  # a panel
    # 'echo' / 'publish' on the switch, if it isn't the mode already
    'mode': lambda nav, mode: nav.entry_mode() != mode and nav._switch_mode('click', mode),
    'verb': lambda nav, name: nav._primary('click') if name == 'primary' else nav._verb(name, 'click'),  # a button
    'search': lambda nav, _: nav._open(Search(), 'click', 'search everything'),  # the top bar's search box
}

# keymap action name -> what it does, given the key (Press; `arg` from its keymap row). Every action
# in keymap.KEYMAP is here, and nothing else (test_keymap).
ACTIONS: dict[str, Callable[[NavState, Press], None]] = {
    # overlays
    'which_key': lambda nav, p: nav._open(WhichKey('all')),
    'g_prefix': lambda nav, p: nav._open(WhichKey('g')),
    'g_cancel': lambda nav, p: nav.feedback.log_line('esc', 'g canceled'),
    'close_overlay': lambda nav, p: nav._close_overlay(p.how),
    # field helper: the entry opens it and writes its value (entries/message.py); its keys go to it
    'helper_key': lambda nav, p: nav.overlay.press(p.key, p.char),
    # command line
    'cmd_open': lambda nav, p: nav._open(CommandLine()),
    'cmd_type': lambda nav, p: nav.overlay.edit(nav.overlay.q + p.char),
    'cmd_back': lambda nav, p: nav._cmd_backspace(),
    'cmd_complete': lambda nav, p: nav.overlay.complete(),
    'cmd_move': lambda nav, p: nav.overlay.move(p.arg),
    'cmd_run': lambda nav, p: nav._cmd_enter(),
    # activity log
    'log_step': lambda nav, p: nav._log_goto(nav.overlay.cur + p.arg),
    'log_end': lambda nav, p: nav._log_goto(len(nav.feedback.activity) if p.arg else 0),
    'log_enter': lambda nav, p: nav._log_enter(),
    # search
    'search_open': lambda nav, p: nav._open(Search(), p.how, 'search everything'),
    'search_type': lambda nav, p: nav.overlay.edit(nav.overlay.q + p.char),
    'search_back': lambda nav, p: nav.overlay.edit(nav.overlay.q[:-1]),
    'search_step': lambda nav, p: nav._search_step(p.arg),
    'search_enter': lambda nav, p: nav._search_enter(p.how),
    # insert
    'edit_keep': lambda nav, p: nav._commit_edit(p.how),
    'edit_step': lambda nav, p: nav._edit_step(p.how, p.arg),
    'edit_back': lambda nav, p: nav._backspace(),
    'edit_type': lambda nav, p: nav._type_char(p.char),
    # layers
    'go_down': lambda nav, p: nav._go_down(p.how),
    'go_up': lambda nav, p: nav._go_up(p.how),
    # moving (arg: the step, or for move_end True for the bottom)
    'move_end': lambda nav, p: nav._move_end(p.how, p.arg),
    'step_tab_cursor': lambda nav, p: setattr(nav, 'tab_cur', _cycle(nav.tab_cur, p.arg, len(nav.tabs))),
    'step_list': lambda nav, p: setattr(nav, 'list_cur', _clamp(nav.list_cur + p.arg,
                                                                len(nav.catalog.rows(nav.chip)) - 1)),
    'step_chip': lambda nav, p: nav._set_chip(_cycle(nav.chip, p.arg, len(KINDS)), p.how),
    'step_area': lambda nav, p: nav._step_area(p.arg),
    'step_row': lambda nav, p: nav._step_row(p.arg),
    'edit': lambda nav, p: nav._edit_row(p.how, clear=bool(p.arg)),  # arg: clear it first
    # tabs
    'goto_tab': lambda nav, p: nav._goto_tab(p.key),
    'step_tab': lambda nav, p: nav._activate(_cycle(nav.active, p.arg, len(nav.tabs)), p.how),
    'close': lambda nav, p: nav._close_tab(nav.tab_cur if nav.layer == TABS else nav.active, p.how),
    'undo': lambda nav, p: nav._undo(p.how),
    # verbs: the entry's own (arg: its name), and those NavState prepares first
    'verb': lambda nav, p: nav._verb(p.arg, p.how),
    'primary': lambda nav, p: nav._primary(p.how),
    'switch_mode': lambda nav, p: nav._switch_mode(p.how),
    'helper': lambda nav, p: nav._open_helper(p.how),
}
