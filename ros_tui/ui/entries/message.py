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

"""The base of the entry kinds that edit a message in field rows: a service's request (now), a
topic's message and an action's goal (next).

`MessageEntry` holds one `MessageData` per entry: the editor's `FieldRows`, the validator, the send
history and its position. The message type is imported in a worker thread when the tab is first
opened (`work`), so the UI never waits on it; until it is in, the editor says "loading…". It ports
the design's 'msg' branches of startEdit / commitEdit / undo and its hist():

- enter / i / a / c edit a row; a typed value is parsed by its row and checked by `build_message`
  before it is kept. A kept edit is one undo step in this tab.
- enter on a folded row unfolds it; h / l fold and unfold (h on a field goes up to its parent).
- o adds a list element after the cursor and starts editing it; d deletes one. Each is one undo step.
- [ and ] step through what was sent from this entry, newest first; ] past the newest brings back
  what you were typing (the draft).

Subclasses send (`verb('primary')`) and may show more areas (`form`).
"""

import functools
from dataclasses import dataclass, field
from typing import Any, Callable

from ros_tui.constants import SEND_HISTORY_MAX
from ros_tui.ros.message_yaml import build_message, import_type, message_structure, message_to_plain, request_class
from ros_tui.ui.entries.base import BridgeEntry, Post, Work
from ros_tui.ui.fields import FieldRows, describe, path_text
from ros_tui.ui.nav import Area, Commit, Editing, NavState, Tab, UndoEntry

FIELDS = 'fields'  # UndoEntry kind of a change to an entry's field rows; data is (what, values before).
EDITOR = 'msg'  # The area id of the editor.

Build = Callable[[dict], tuple[Any, list]]  # Plain values -> (message, time setters); raises FieldError.


@dataclass
class Loaded:
    """What the worker thread imports for an entry's type."""

    fields: tuple  # The editor's FieldNodes.
    seed: dict  # The default message as plain values (a nested header as 'auto').
    build: Build
    extra: Any = None  # What the entry kind loads alongside (a service's response structure).


@dataclass
class MessageData:
    type: str = ''
    editor: FieldRows | None = None  # None until the type is loaded.
    build: Build | None = None
    extra: Any = None
    loading: bool = False
    error: str = ''  # Why the type could not be loaded.
    history: list[dict] = field(default_factory=list)  # What was sent, newest first.
    hpos: int = -1  # The history entry shown in the editor (-1: your own edit).
    draft: dict | None = None  # Your own edit, kept while [ ] show older sends.


class MessageEntry(BridgeEntry):
    """An entry kind with a message editor (area EDITOR) in field rows."""

    KIND = 'msg'  # The interface kind (msg, srv, action) that message_yaml loads.

    def __init__(self, bridge: Any, post: Post | None = None, work: Work | None = None):
        super().__init__(bridge, post, work)
        self._data: dict[str, MessageData] = {}

    def new_data(self) -> MessageData:
        return MessageData()

    def data(self, tab: Tab) -> MessageData:
        return self._data.setdefault(tab.key, self.new_data())

    def form(self, tab: Tab, area: Area | None) -> FieldRows | None:
        """The field rows an area shows: the editor, or what a subclass adds."""
        return self.data(tab).editor if area is not None and area.id == EDITOR else None

    def area_named(self, tab: Tab, area_id: str) -> Area | None:
        return next((area for area in self.areas(tab) if area.id == area_id), None)

    # ---------- loading ----------
    def on_open(self, nav: NavState, tab: Tab) -> None:
        """Import the entry's type in a worker the first time its tab opens."""
        data = self.data(tab)
        if data.editor is not None or data.loading:
            return
        item = nav.item(tab)
        if item is None or not item.type:
            data.error = 'no type information for this entry'
            return
        data.type, data.loading, data.error = item.type, True, ''
        self._work(lambda: self._load(tab.key, item.type))

    def load_types(self, type_name: str) -> Loaded:
        """In the worker thread: import the type and build the editor's structure and seed."""
        interface = import_type(self.KIND, type_name)
        fillable = request_class(self.KIND, interface)
        return Loaded(message_structure(self.KIND, type_name), message_to_plain(fillable(), seed=True),
                      functools.partial(build_message, fillable), self.load_extra(interface))

    def load_extra(self, interface: type) -> Any:
        return None

    def _load(self, key: str, type_name: str) -> None:
        try:
            loaded, error = self.load_types(type_name), ''
        except Exception as failure:  # noqa: BLE001 - shown in the editor instead of crashing the worker
            loaded, error = None, str(failure)
        self._post(lambda: self._loaded(key, loaded, error))

    def _loaded(self, key: str, loaded: Loaded | None, error: str) -> None:
        data = self._data[key]
        data.loading = False
        data.error = error
        if loaded is not None:
            data.editor = FieldRows(loaded.fields, loaded.seed)
            data.build = loaded.build
            data.extra = loaded.extra

    # ---------- rows ----------
    def row_count(self, tab: Tab, area: Area) -> int:
        form = self.form(tab, area)
        return len(form.rows()) if form else 0

    def activate_row(self, nav: NavState, tab: Tab, area: Area, row: int, how: str) -> bool:
        """enter on a nested message or list folds or unfolds it."""
        form = self.form(tab, area)
        text = form.toggle(row) if form else None
        if text is None:
            return False
        nav.log_line(how, text)
        return True

    def enter_label(self, tab: Tab, area: Area, row: int) -> str | None:
        form = self.form(tab, area)
        current = form.row(row) if form else None
        if current is None or not current.folds:
            return None
        return 'fold' if current.open else 'unfold'

    # ---------- editing ----------
    def start_edit(self, tab: Tab, area: Area, row: int, clear: bool) -> Editing | None:
        form = self.form(tab, area) if area.editable else None
        current = form.row(row) if form else None
        if current is None or not current.editable:
            return None
        text = '' if clear else current.edit_text()
        return Editing(area.id, row, text, old=text, fresh=current.fresh, field=current.field)

    def commit_edit(self, tab: Tab, editing: Editing) -> Commit:
        data = self.data(tab)
        form = data.editor
        index = form.index_of(editing.field) if form else None  # By field: rows can fold meanwhile.
        if index is None:
            return Commit(False, f'{editing.field} is no longer in the message')
        before = form.to_plain()
        try:
            old, new = form.accept(index, editing.value, data.build)
        except ValueError as error:
            return Commit(False, str(error))
        shown = form.row(index).text
        if new == old:
            return Commit(True, f'kept {editing.field} = {shown}')
        return Commit(True, f'kept {editing.field} = {shown} (u undoes)',
                      UndoEntry(tab.key, FIELDS, (f'the edit of {editing.field}', before)))

    def undo(self, nav: NavState, entry: UndoEntry) -> str:
        what, before = entry.data
        tab = Tab(*entry.owner.split(':', 1))
        self.data(tab).editor.load(before)
        return f'undid {what} on {tab.name}'

    # ---------- verbs ----------
    def verb(self, nav: NavState, tab: Tab | None, name: str, how: str, arg: Any = None) -> bool:
        if name in ('fold', 'unfold'):
            self._fold(nav, tab, how, name == 'unfold')
        elif name == 'add_item':
            self._change_list(nav, tab, how, add=True)
        elif name == 'delete_item':
            self._change_list(nav, tab, how, add=False)
        elif name in ('history_older', 'history_newer'):
            self.step_history(nav, tab, how, older=name == 'history_older')
        else:
            return super().verb(nav, tab, name, how, arg)
        return True

    def _fold(self, nav: NavState, tab: Tab, how: str, unfold: bool) -> None:
        area = nav.area()
        form = self.form(tab, area)
        index = nav.row_index(area)
        moved = (form.unfold(index) if unfold else form.fold(index)) if form else None
        if moved is None:
            nav.log_line(how, 'nothing to unfold here' if unfold else 'already at the top — esc goes back up')
            return
        nav.set_row(moved[0], area)
        nav.log_line(how, moved[1])

    def _change_list(self, nav: NavState, tab: Tab, how: str, add: bool) -> None:
        """o / d: add an element after the cursor (and edit it), or delete the one under it."""
        area = nav.area()
        form = self.form(tab, area)
        if form is None:
            nav.hint(how)
            return
        before = form.to_plain()
        try:
            if add:
                path = target = form.add_item(nav.row_index(area))
            else:
                path, target = form.delete_item(nav.row_index(area))
        except ValueError as error:
            nav.show_toast(str(error), 'bad')
            nav.log_line(how, str(error))
            return
        what = f'{"adding" if add else "deleting"} {path_text(path)}'
        nav.push_undo(UndoEntry(tab.key, FIELDS, (what, before)))
        nav.set_row(form.index_of(target), area)
        nav.log_line(how, f'{"added" if add else "deleted"} {path_text(path)} (u undoes)')
        if add:
            nav.start_edit(how)

    # ---------- sending ----------
    def checked(self, nav: NavState, tab: Tab, how: str) -> tuple[Any, list] | None:
        """The editor's message and its time setters, built and checked before a send. A bad value
        is revealed in the editor (the cursor goes to it) with an errline; nothing is sent."""
        data = self.data(tab)
        form = data.editor
        if form is None or data.build is None:
            text = f'could not load {data.type}: {data.error}' if data.error else 'still loading the message type'
            nav.show_toast(text, 'bad')
            nav.log_line(how, f'{text} — nothing sent')
            return None
        try:
            return data.build(form.to_plain())
        except Exception as error:  # noqa: BLE001 - a FieldError, shown on its row
            path = getattr(error, 'path', None)
            if path is None:
                raise
            message = describe(error)
            form.bad = path
            nav.set_row(form.reveal(path), self.area_named(tab, EDITOR))
            nav.report_error(tab, message)
            nav.show_toast('fix the highlighted values first', 'bad')
            nav.log_line(how, f'✗ {message} — nothing sent')
            return None

    def remember(self, tab: Tab) -> dict:
        """A send: the editor's values go to the front of the entry's history."""
        data = self.data(tab)
        values = data.editor.to_plain()
        data.history.insert(0, values)
        del data.history[SEND_HISTORY_MAX:]
        data.hpos, data.draft = -1, None
        return values

    def step_history(self, nav: NavState, tab: Tab, how: str, older: bool) -> None:
        """[ / ]: show an older / newer send in the editor; ] past the newest restores your edit."""
        data = self.data(tab)
        history = data.history
        if not history or data.editor is None:
            nav.log_line(how, 'no history for this entry yet')
            nav.show_toast('send something first', 'bad')
            return
        current = data.editor.to_plain()
        if data.hpos < 0:
            data.draft = current
        position = data.hpos + (1 if older else -1)
        if older and data.hpos < 0 and len(history) > 1 and history[0] == current:
            position = 1  # The newest send is what the editor already shows.
        if position > len(history) - 1:
            nav.show_toast('that was the oldest send', 'info')
            position = len(history) - 1
        data.hpos = max(-1, position)
        if data.hpos < 0:
            if data.draft is not None:
                data.editor.load(data.draft)
            nav.log_line(how, 'back to your own edit')
            return
        data.editor.load(history[data.hpos])
        nav.log_line(how, f'loaded send {data.hpos + 1} of {len(history)} (1 = newest) · ] goes newer')
