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

"""The contract between `NavState` and the entry kinds: `Entry` and the types it answers with.

NavState makes one `Entry` per `Tab` the first time it needs it (through the factory it is given,
`kinds.entry_factory` in the app) and keeps it after the tab closes, so an entry's edits, history
and echo survive a close and reopen. NavState asks an entry what it shows (`areas`, `row_count`,
labels) and hands it what you do (`start_edit` / `commit_edit`, `activate_row`, its `verbs`).
An entry talks back through `nav.feedback` (`log_line`, `refuse`, `report_error`,
`add_activity`, …) and NavState's few calls for entries (`push_undo`, `begin_edit`, `set_row`,
…). Pure Python: this module imports nothing of the UI, so nav.py can import it.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, NamedTuple

if TYPE_CHECKING:
    from ros_tui.ui.nav import NavState

Post = Callable[[Callable[[], None]], None]
Work = Post
Verb = Callable[['NavState', str, Any], None]  # (nav, how the key reads in the log, the argument or None).


@dataclass(frozen=True)
class Tab:
    kind: str  # One of catalog.KINDS.
    name: str


@dataclass(frozen=True)
class Area:
    """One panel of an entry. Ids: msg, out, ifs, par."""

    id: str
    title: str  # In capitals; the breadcrumb shows it in lower case.
    enter: str = ''  # Footer "enter …" label inside the area ('' when enter does nothing there).
    editable: bool = False  # i / a / c and enter edit its rows.
    folds: bool = False  # Its rows are field rows that fold (h / l; o / d where editable).
    helpers: bool = False  # Its rows may have a field helper (f).


@dataclass
class Editing:
    """The value being typed in the EDIT layer."""

    area: str  # The area id it belongs to, or an editor's own id outside the areas ('rate').
    row: int
    value: str
    old: str = ''
    fresh: bool = False  # The first typed character replaces the value instead of appending.
    field: str = ''  # The field as the user sees it, for log lines.
    note: str = '(insert)'  # Appended to the "edit <field>" log line.
    crumb: tuple[str, ...] = ()  # Breadcrumb parts instead of the area title, e.g. ('repeat rate',).
    back: str | None = None  # The layer to return to when the edit ends (None: the one it started on).


@dataclass(frozen=True)
class UndoEntry:
    """One undo step: `revert` undoes it and returns the log line."""

    owner: Tab | None  # The tab it was made in; None for one any tab can undo (a closed tab).
    revert: Callable[['NavState'], str]
    tag: Any = None  # What it changed, for `NavState.drop_undo` (a parameter's name).


@dataclass(frozen=True)
class Commit:
    """An entry's answer to committing an edit: kept (with a log line), or an error message."""

    ok: bool
    text: str
    undo: UndoEntry | None = None
    activity: tuple[str, str] = ()  # (text, cls) of an activity line it causes, e.g. a running repeat's new rate.


class Running(NamedTuple):
    """Something an entry has running, as the tab row, the top bar and the Here column show it."""

    glyph: str  # '◉' an echo, '↻' a repeating publish, a frame of the '◐◓◑◒' spinner for a goal executing.
    label: str  # The Here column's words: 'echoing', '10 Hz', 'running'.
    tone: str  # The theme token it is drawn in: 'live' or 'ok'.


class Context:
    """What the entries share: the bridge (a RosBridge or FakeBridge), `post` and `work`, and objects
    shared by every entry of a kind (`single`). The bridge answers on its own thread; an entry wraps
    every answer in `post(fn)`, which runs `fn` on the UI thread. Slow work that isn't a bridge call
    (importing an interface type) goes to `work(fn)`, which runs `fn` in a worker thread; `fn` posts
    its result too. Without a `post` or `work` (unit tests over a bridge that answers in place) `fn`
    runs straight away."""

    def __init__(self, bridge: Any = None, post: Post | None = None, work: Work | None = None):
        self.bridge = bridge
        self.post = post or (lambda fn: fn())
        self.work = work or (lambda fn: fn())
        self._singles: dict[type, Any] = {}

    def single(self, cls: type) -> Any:
        """The one `cls()` every entry over this context shares (the action entries' one running goal)."""
        return self._singles.setdefault(cls, cls())


class Entry:
    """What one entry holds and does. NavState asks; each entry kind subclasses it (entries/kinds.py).

    The base has the areas its kind declares (`AREAS`, or per mode `MODES`), no rows and no verbs.
    Hooks that take `nav` may change it (log, toast, push undo, open a tab); the others only answer.
    """

    AREAS: tuple[Area, ...] = ()
    MODES: dict[str, tuple[Area, ...]] = {}  # Mode -> its areas, for a kind with modes (a topic's echo / publish).

    def __init__(self, tab: Tab, ctx: Context | None = None):
        self.tab = tab
        self._ctx = ctx = ctx or Context()
        self._bridge, self._post, self._work = ctx.bridge, ctx.post, ctx.work
        self.mode = ''  # One of MODES, once the entry has opened (`on_open` picks it).

    def modes(self) -> tuple[str, ...]:
        """The modes `e` switches between, in order; () for a kind without them."""
        return tuple(self.MODES)

    def areas(self) -> tuple[Area, ...]:
        return self.MODES.get(self.mode, ()) if self.MODES else self.AREAS

    def area_named(self, area_id: str) -> Area | None:
        return next((area for area in self.areas() if area.id == area_id), None)

    def on_open(self, nav: 'NavState') -> None:
        """Its tab was opened or gone to."""

    def on_close(self, nav: 'NavState') -> list[str]:
        """Its tab is being closed: stop what nothing could stop once it is gone (an echo, a
        repeat). Returns what it stopped, for the log line ('echo stopped'). A running goal keeps
        running: canceling it would be a send."""
        return []

    def row_count(self, area: Area) -> int:
        return 0

    def start_edit(self, area: Area, row: int, clear: bool) -> Editing | None:
        """An Editing for the row, or None when it can't be edited."""
        return None

    def commit_edit(self, editing: Editing) -> Commit:
        return Commit(True, f'kept {editing.field or "the value"}')

    def activate_row(self, nav: 'NavState', area: Area, row: int, how: str) -> bool:
        """enter on a row, before it is edited: open an interface, show / hide a field, fold or
        unfold a nested message or list. True if done (then the row isn't edited)."""
        return False

    def leave_area(self, area: Area) -> str | None:
        """esc out of an area: a log line instead of "up one layer" (e.g. a frozen echo goes live)."""
        return None

    def esc_label(self, area: Area) -> str | None:
        """The footer's esc label inside an area, when it isn't the default ('go live')."""
        return None

    def enter_label(self, area: Area, row: int) -> str | None:
        """The footer's enter label on a row, when it isn't the area's ('unfold' on a folded row)."""
        return None

    def helper_name(self, area: Area, row: int) -> str | None:
        """'Quaternion' when the row has a field helper."""
        return None

    def label_vars(self) -> dict[str, Any]:
        """Values for keymap labels, e.g. the repeat rate in "repeat at {rate} Hz"."""
        return {}

    def running(self) -> tuple[Running, ...]:
        """What runs in this entry (an echo, a repeat, a goal), whether its tab is open or not."""
        return ()

    def tick(self, nav: 'NavState') -> bool:
        """The clock ticked: take in what arrived (an echo's messages). True when the views should redraw."""
        return False

    def verbs(self) -> dict[str, Verb]:
        """The verbs this entry offers now, by name: primary, secondary, repeat, rate, set_rate,
        helper, helper_apply, history_older, history_newer, yank, paste, and on field rows fold,
        unfold, add_item, delete_item. NavState says a verb missing here isn't available."""
        return {}
