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

"""The base of the entry kinds that edit a message in field rows: a service's request, a
topic's message and an action's goal.

`MessageEntry` holds the editor's `FieldRows`, the validator, the send history and its position.
The message type is imported in a worker thread when the tab is first opened (`work`), so the UI
never waits on it; until it is in, the editor says "loading…".

- enter / i / a / c edit a row; a typed value is parsed by its row and checked by `build_message`
  before it is kept. A kept edit is one undo step in this tab.
- enter on a folded row unfolds it; h / l fold and unfold (h on a field goes up to its parent).
- o adds a list element after the cursor and starts editing it; d deletes one. Each is one undo step.
- [ and ] step through what was sent from this entry, newest first; ] past the newest brings back
  what you were typing (the draft).
- f on a row with a field helper (helpers/) opens it; enter writes its value into the row, as one
  undo step, and esc leaves the row as it was.
- y copies the editor's message into the register (register.py); p pastes the register into the
  editor when it holds the same type in the same role (a topic's message, a service's request, an
  action's goal), as one undo step.

Subclasses add their sending verb (`primary`, starting with `_send`), say what the editor holds
(`ROLE`) and may show more areas (`form`).
"""

import functools
from dataclasses import dataclass
from typing import Any, Callable

from ros_tui.constants import SEND_HISTORY_MAX, SUMMARY_MAX_CHARS
from ros_tui.ros.message_yaml import (build_message, import_type, message_structure, message_to_display,
                                      message_to_plain, request_class)
from ros_tui.ui.entries.base import Area, Commit, Context, Editing, Entry, Tab, UndoEntry, Verb
from ros_tui.ui.fields import FieldRows, Row, describe, flow_yaml, path_text, summary
from ros_tui.ui.helpers import Helper, helper_name
from ros_tui.ui.nav import NavState
from ros_tui.ui.register import Register

EDITOR = 'msg'  # The area id of the editor.

Build = Callable[[dict], tuple[Any, list]]  # Plain values -> (message, time setters); raises FieldError.


class Received:
    """A message as it arrived (an echoed one, a goal's feedback), kept for an exact y. Its display
    values (long arrays and strings cut) are converted the first time it is shown, so a fast topic
    or one in a background tab costs no conversion per tick."""

    def __init__(self, message: Any):
        self.message = message

    @functools.cached_property
    def display(self) -> dict:
        return message_to_display(self.message)


@dataclass
class Loaded:
    """What the worker thread imports for an entry's type."""

    fields: tuple  # The editor's FieldNodes.
    seed: dict  # The default message as plain values (a nested header as 'auto').
    build: Build
    extra: Any = None  # What the entry kind loads alongside (a service's response structure).


class MessageEntry(Entry):
    """An entry kind with a message editor (area EDITOR) in field rows."""

    KIND = 'msg'  # The interface kind (msg, srv, action) that message_yaml loads.
    ROLE = 'message'  # What its editor holds, for the register: a topic's message, a service's request, …

    def __init__(self, tab: Tab, ctx: Context | None = None):
        super().__init__(tab, ctx)
        self.type = ''
        self.editor: FieldRows | None = None  # None until the type is loaded.
        self.build: Build | None = None
        self.extra: Any = None
        self.loading = False
        self.error = ''  # Why the type could not be loaded.
        self.history: list[dict] = []  # What was sent, newest first.
        self.hpos = -1  # The history entry shown in the editor (-1: your own edit).
        self.draft: dict | None = None  # Your own edit, kept while [ ] show older sends.

    def not_loaded(self) -> str:
        """Why there is no editor yet: the type is still loading, or why it failed to."""
        if not self.error:
            return 'still loading the message type'
        return f'could not load {self.type}: {self.error}' if self.type else self.error

    def form(self, area: Area | None) -> FieldRows | None:
        """The field rows an area shows: the editor, or what a subclass adds."""
        return self.editor if area is not None and area.id == EDITOR else None

    # ---------- loading ----------
    def on_open(self, nav: NavState) -> None:
        """Import the entry's type in a worker the first time its tab opens."""
        if self.editor is not None or self.loading:
            return
        item = nav.catalog.item(self.tab)
        if item is None or not item.type:
            self.error = 'no type information for this entry'
            return
        self.type, self.loading, self.error = item.type, True, ''
        self._work(lambda: self._load(item.type))

    def load_types(self, type_name: str) -> Loaded:
        """In the worker thread: import the type and build the editor's structure and seed."""
        interface = import_type(self.KIND, type_name)
        fillable = request_class(self.KIND, interface)
        return Loaded(message_structure(self.KIND, type_name), message_to_plain(fillable(), seed=True),
                      functools.partial(build_message, fillable), self.load_extra(interface))

    def load_extra(self, interface: type) -> Any:
        return None

    def _load(self, type_name: str) -> None:
        try:
            loaded, error = self.load_types(type_name), ''
        except Exception as failure:  # noqa: BLE001 - shown in the editor instead of crashing the worker
            loaded, error = None, str(failure)
        self._post(lambda: self._loaded(loaded, error))

    def _loaded(self, loaded: Loaded | None, error: str) -> None:
        self.loading = False
        self.error = error
        if loaded is not None:
            self.editor = FieldRows(loaded.fields, loaded.seed)
            self.build = loaded.build
            self.extra = loaded.extra

    # ---------- rows ----------
    def row_count(self, area: Area) -> int:
        form = self.form(area)
        return len(form.rows()) if form else 0

    def activate_row(self, nav: NavState, area: Area, row: int, how: str) -> bool:
        """enter on a nested message or list folds or unfolds it."""
        form = self.form(area)
        text = form.toggle(row) if form else None
        if text is None:
            return False
        nav.feedback.log_line(how, text)
        return True

    def enter_label(self, area: Area, row: int) -> str | None:
        form = self.form(area)
        current = form.row(row) if form else None
        if current is None or not current.folds:
            return None
        return 'fold' if current.open else 'unfold'

    def helper_name(self, area: Area, row: int) -> str | None:
        return helper_name(self._edit_row(area, row))

    # ---------- editing ----------
    def _edit_row(self, area: Area | None, row: int) -> Row | None:
        """Row `row` of an area you edit (the message, the request, the goal), or None."""
        form = self.form(area) if area is not None and area.editable else None
        return form.row(row) if form else None

    def start_edit(self, area: Area, row: int, clear: bool) -> Editing | None:
        current = self._edit_row(area, row)
        if current is None or not current.editable:
            return None
        text = '' if clear else current.edit_text()
        return Editing(area.id, row, text, old=text, fresh=current.fresh, field=current.field)

    def commit_edit(self, editing: Editing) -> Commit:
        try:
            shown, undo = self._write(editing.field, editing.value, 'the edit of')
        except ValueError as error:
            return Commit(False, str(error))
        return Commit(True, f'kept {editing.field} = {shown}' + (' (u undoes)' if undo else ''), undo)

    def _write(self, field: str, text: str, what: str) -> tuple[str, UndoEntry | None]:
        """Keep `text` as the value of `field` (by field: rows can fold meanwhile): (the value as
        its row shows it, the undo step, or None when nothing changed). ValueError with the user's
        message when it doesn't parse or validate."""
        form = self.editor
        index = form.index_of(field) if form else None
        if index is None:
            raise ValueError(f'{field} is no longer in the message')
        before = form.to_plain()
        old, new = form.accept(index, text, self.build)
        return form.row(index).text, self._undo_step(f'{what} {field}', before) if new != old else None

    def _undo_step(self, what: str, before: dict) -> UndoEntry:
        """The undo step of a change to the editor: it loads `before` back."""
        def revert(nav: NavState) -> str:
            self.editor.load(before)
            return f'undid {what} on {self.tab.name}'
        return UndoEntry(self.tab, revert)

    # ---------- verbs ----------
    def verbs(self) -> dict[str, Verb]:
        return {
            'fold': lambda nav, how, _: self._fold(nav, how, unfold=False),
            'unfold': lambda nav, how, _: self._fold(nav, how, unfold=True),
            'add_item': lambda nav, how, _: self._change_list(nav, how, add=True),
            'delete_item': lambda nav, how, _: self._change_list(nav, how, add=False),
            'history_older': lambda nav, how, _: self._step_history(nav, how, older=True),
            'history_newer': lambda nav, how, _: self._step_history(nav, how, older=False),
            'helper': lambda nav, how, _: self._open_helper(nav, how),
            'helper_apply': lambda nav, how, _: self._apply_helper(nav, how),
            'yank': lambda nav, how, _: self._yank(nav, how),
            'paste': lambda nav, how, _: self._paste(nav, how),
        }

    # ---------- the register ----------
    def _loaded_editor(self, nav: NavState, how: str) -> FieldRows | None:
        """The editor, or None (with a toast) while its type is still loading or failed to load."""
        if self.editor is None:
            nav.feedback.refuse(how, self.not_loaded())
        return self.editor

    def _yank(self, nav: NavState, how: str) -> None:
        """y: copy what the editor holds."""
        editor = self._loaded_editor(nav, how)
        if editor is None:
            return
        nav.register = Register.of(self.type, self.ROLE, self.tab.name, editor.to_plain())
        nav.feedback.show_toast(f'copied the {self.ROLE}', 'info')
        nav.feedback.log_line(how, f'copied the {self.ROLE} of {self.tab.name} — p pastes it')

    def _paste(self, nav: NavState, how: str) -> None:
        """p: replace the editor's message with the register's, if it is the same type and role, as
        one undo step."""
        register = nav.register
        if register is None:
            nav.feedback.refuse(how, 'nothing copied yet (y copies)', 'nothing copied yet')
            return
        editor = self._loaded_editor(nav, how)
        if editor is None:
            return
        wrong = register.mismatch(self.type, self.ROLE)
        if wrong:
            nav.feedback.refuse(how, wrong, f'✗ {wrong} — not pasted')
            return
        before = editor.to_plain()
        editor.load(register.values)
        self.hpos, self.draft = -1, None
        nav.feedback.clear_error(self.tab)
        if before == register.values:
            nav.feedback.show_toast(f'pasted from {register.source} · it was the same already', 'info')
            nav.feedback.log_line(how, f'pasted from {register.source}: nothing changed')
            return
        nav.push_undo(self._undo_step(f'the paste from {register.source}', before))
        nav.feedback.show_toast(f'pasted from {register.source} · u undoes', 'info')
        nav.feedback.log_line(how, f'pasted the {register.label} from {register.source} (u undoes)')

    # ---------- field helpers ----------
    def _open_helper(self, nav: NavState, how: str) -> None:
        """f on a row with a helper opens its popup; NavState only asks on
        a row that has one (`helper_name`)."""
        helper = Helper.open(self._edit_row(nav.area(), nav.row_index()))
        if helper is not None:
            nav.overlay = helper
            nav.feedback.log_line(how, f'opened the {helper.name} helper for {helper.field}')

    def _apply_helper(self, nav: NavState, how: str) -> None:
        """enter in the helper writes its value into the row, as one undo step. While its fields make no
        value it stays open."""
        helper = nav.overlay
        result = helper.result()
        if result is None:
            nav.feedback.refuse(how, 'fix the highlighted values first',
                                '✗ the helper has no value yet — fix the values first')
            return
        try:
            shown, undo = self._write(helper.field, flow_yaml(result.value), f'the {helper.name} helper on')
        except ValueError as error:
            nav.feedback.refuse(how, str(error), f'✗ {error}')
            return
        nav.overlay = None  # It opened on this row inside the area, so the cursor is where it was.
        nav.feedback.clear_error(self.tab)
        if undo:
            nav.push_undo(undo)
        nav.feedback.log_line(how, f'filled {helper.field} = {shown}' + (' (u undoes)' if undo else ''))

    def _fold(self, nav: NavState, how: str, unfold: bool) -> None:
        area = nav.area()
        form = self.form(area)
        index = nav.row_index(area)
        moved = (form.unfold(index) if unfold else form.fold(index)) if form else None
        if moved is None:
            nav.feedback.log_line(how, 'nothing to unfold here' if unfold else 'already at the top — esc goes back up')
            return
        nav.set_row(moved[0], area)
        nav.feedback.log_line(how, moved[1])

    def _change_list(self, nav: NavState, how: str, add: bool) -> None:
        """o / d: add an element after the cursor (and edit it), or delete the one under it."""
        area = nav.area()
        form = self.form(area)
        if form is None:
            nav.feedback.hint(how)
            return
        before = form.to_plain()
        try:
            if add:
                path = target = form.add_item(nav.row_index(area))
            else:
                path, target = form.delete_item(nav.row_index(area))
        except ValueError as error:
            nav.feedback.refuse(how, str(error))
            return
        nav.push_undo(self._undo_step(f'{"adding" if add else "deleting"} {path_text(path)}', before))
        nav.set_row(form.index_of(target), area)
        nav.feedback.log_line(how, f'{"added" if add else "deleted"} {path_text(path)} (u undoes)')
        if add:
            nav.start_edit(how)

    # ---------- sending ----------
    def _checked(self, nav: NavState, how: str) -> tuple[Any, list] | None:
        """The editor's message and its time setters, built and checked before a send. A bad value
        is revealed in the editor (the cursor goes to it) with an errline; nothing is sent."""
        form = self.editor
        if form is None or self.build is None:
            text = self.not_loaded()
            nav.feedback.refuse(how, text, f'{text} — nothing sent')
            return None
        try:
            return self.build(form.to_plain())
        except Exception as error:  # noqa: BLE001 - a FieldError, shown on its row
            path = getattr(error, 'path', None)
            if path is None:
                raise
            message = describe(error)
            form.bad = path
            nav.set_row(form.reveal(path), self.area_named(EDITOR))
            nav.feedback.report_error(self.tab, message)
            nav.feedback.refuse(how, 'fix the highlighted values first', f'✗ {message} — nothing sent')
            return None

    def _ready(self, nav: NavState, how: str) -> tuple[Any, tuple, str] | None:
        """The start of every send (space / ^s, r): the checked message, which goes into the history
        and clears the errline. (message, time setters, the message summarised), or None when it
        doesn't check out (see `_checked`)."""
        built = self._checked(nav, how)
        if built is None:
            return None
        message, time_setters = built
        sent = summary(self._remember(), SUMMARY_MAX_CHARS)
        nav.feedback.clear_error(self.tab)
        return message, tuple(time_setters), sent

    def _send(self, nav: NavState, how: str, line: str, cls: str, log: str) -> tuple[Any, tuple, str] | None:
        """space / ^s: `_ready`, then the primary button flashes, the activity line `line` (with
        the message summarised after it) and the log line `log`. The caller sends it."""
        ready = self._ready(nav, how)
        if ready is not None:
            nav.feedback.flash_send(self.tab)
            nav.feedback.add_activity(self.tab, f'{line} · {ready[2]}' if ready[2] else line, cls)
            nav.feedback.log_line(how, log)
        return ready

    def _remember(self) -> dict:
        """A send: the editor's values go to the front of the entry's history."""
        values = self.editor.to_plain()
        self.history.insert(0, values)
        del self.history[SEND_HISTORY_MAX:]
        self.hpos, self.draft = -1, None
        return values

    def _step_history(self, nav: NavState, how: str, older: bool) -> None:
        """[ / ]: show an older / newer send in the editor; ] past the newest restores your edit."""
        history = self.history
        if not history or self.editor is None:
            nav.feedback.refuse(how, 'send something first', 'no history for this entry yet')
            return
        current = self.editor.to_plain()
        if self.hpos < 0:
            self.draft = current
        position = self.hpos + (1 if older else -1)
        if older and self.hpos < 0 and len(history) > 1 and history[0] == current:
            position = 1  # The newest send is what the editor already shows.
        if position > len(history) - 1:
            nav.feedback.show_toast('that was the oldest send', 'info')
            position = len(history) - 1
        self.hpos = max(-1, position)
        if self.hpos < 0:
            if self.draft is not None:
                self.editor.load(self.draft)
            nav.feedback.log_line(how, 'back to your own edit')
            return
        self.editor.load(history[self.hpos])
        nav.feedback.log_line(how, f'loaded send {self.hpos + 1} of {len(history)} (1 = newest) · ] goes newer')
