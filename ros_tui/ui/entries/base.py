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

"""The contract between `NavState` and the entry kinds: `Entry`, the types it answers with, and
`Host`, what an entry may ask of NavState.

NavState makes one `Entry` per `Tab` the first time it needs it (through the factory it is given,
`kinds.entry_factory` in the app) and keeps it after the tab closes, so an entry's edits, history
and echo survive a close and reopen. NavState asks an entry what it shows (`areas`, `row_count`,
labels) and hands it what you do (`start_edit` / `commit_edit`, `activate_row`, its `verbs`).
An entry talks back only through the `Host` it is handed (NavState is the one in the app). Pure
Python: this module imports nothing of the UI at run time, so nav.py can import it.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, NamedTuple, Protocol

if TYPE_CHECKING:
    from ros_tui.ros.contract import Bridge
    from ros_tui.ui.catalog import Catalog
    from ros_tui.ui.feedback import Feedback
    from ros_tui.ui.helpers import Helper
    from ros_tui.ui.register import Register

# The layers, top to bottom: the tab row › inside a tab (the ☰ list, or an entry's area pick) ›
# the rows of one area › typing into one value. An entry names one only as `Editing.back`.
TABS, IN, AREA, EDIT = ('tabs', 'in', 'area', 'edit')

# The area ids (`Area.id`, `Editing.area`). The keymap's predicates and the views ask for an area by
# these, never by its title.
EDITOR = 'msg'  # A message editor: a topic's MESSAGE, a service's REQUEST, an action's GOAL.
OUT = 'out'  # What came back: a topic's LATEST MESSAGE, a service's RESPONSE, an action's RESULT.
IFS = 'ifs'  # A node's INTERFACES.
PARAM = 'par'  # A node's PARAMETERS; its undo steps are tagged with the parameter's name.
RATE = 'rate'  # Not an area: the `Editing.area` of a topic's repeat-rate editor.

Post = Callable[[Callable[[], None]], None]
Work = Post
Verb = Callable[['Host', str, Any], None]  # (nav, how the key reads in the log, the argument or None).


@dataclass(frozen=True)
class Tab:
    kind: str  # One of catalog.KINDS.
    name: str


@dataclass(frozen=True)
class Area:
    """One panel of an entry; its id is one of the area ids above."""

    id: str
    title: str  # In capitals; the breadcrumb shows it in lower case.
    enter: str = ''  # Footer "enter …" label inside the area ('' when enter does nothing there).
    editable: bool = False  # i / a / c and enter edit its rows.
    folds: bool = False  # Its rows are field rows that fold (h / l; o / d where editable).
    helpers: bool = False  # Its rows may have a field helper (f).


@dataclass
class Editing:
    """The value being typed in the EDIT layer."""

    area: str  # The area id it belongs to, or an editor's own id outside the areas (RATE).
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
    revert: Callable[['Host'], str]
    tag: Any = None  # What it changed, for `Host.drop_undo` (a parameter's name).


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
    """What the entries share: the bridge (ros/contract.py says how it answers), `post` and `work`,
    and objects shared by every entry of a kind (`single`). The bridge answers on its own thread; an
    entry wraps every answer in `post(fn)`, which runs `fn` on the UI thread. Slow work that isn't a
    bridge call (importing an interface type) goes to `work(fn)`, which runs `fn` in a worker
    thread; `fn` posts its result too. Without a `post` or `work` (unit tests over a bridge that
    answers in place) `fn` runs straight away. Without a bridge (an entry built with no Context)
    the entry must not call it."""

    def __init__(self, bridge: 'Bridge | None' = None, post: Post | None = None, work: Work | None = None):
        self.bridge = bridge
        self.post = post or (lambda fn: fn())
        self.work = work or (lambda fn: fn())
        self._singles: dict[type, Any] = {}

    def single(self, cls: type) -> Any:
        """The one `cls()` every entry over this context shares (the action entries' one running goal)."""
        return self._singles.setdefault(cls, cls())


class Host(Protocol):
    """What an entry may ask of the UI around it: the `nav` its hooks, verbs and undo steps get.

    NavState is the host in the app; an entry sees nothing of it beyond these members. The
    properties are read-only: an entry changes the UI through the methods, never by assigning.
    "The cursor" is the cursor in the active tab; `how` is how the key reads in the log ('enter',
    ':rate 5'), passed on to the log line.
    """

    # ---------------------------------------------------------------- what it holds

    @property
    def feedback(self) -> 'Feedback':
        """What the UI says back, through its methods only. `log_line(how, text)` for every verb;
        `refuse(how, toast, log=None)` when a verb can't run (a red toast, and `log` or the toast as
        the log line); `report_error(tab, text)` / `clear_error(tab)` for the tab's error line;
        `add_activity(tab, text, cls)` for what ROS answered; `show_toast(text, kind)`,
        `flash_send(tab)` on a send, `hint(how)`; and `clock()` to time a call."""
        ...

    @property
    def catalog(self) -> 'Catalog':
        """What the graph has: `catalog.item(tab)` is the tab's entity (its type, its counts), or None."""
        ...

    @property
    def tab(self) -> Tab | None:
        """The active tab (None on the ☰ list). An entry whose tab isn't it runs in the background."""
        ...

    @property
    def register(self) -> 'Register | None':
        """What y copied last, app-wide, for p (None before the first copy). `copy` replaces it."""
        ...

    @property
    def overlay(self) -> Any:
        """What sits on top and has the keys (a field helper the entry opened, …), or None."""
        ...

    # ---------------------------------------------------------------- where the cursor is

    def area(self) -> Area | None:
        """The area under the cursor, at the area pick or inside it (None on the ☰ list)."""
        ...

    def row_index(self, area: Area | None = None) -> int:
        """The cursor's row in `area` (default: the area under the cursor)."""
        ...

    def inside(self, area_id: str) -> bool:
        """The cursor is in the rows of area `area_id`, or typing into one of them (not at the area
        pick above them). An echo is frozen while the cursor is inside it."""
        ...

    # ---------------------------------------------------------------- what an entry makes happen

    def set_row(self, index: int, area: Area | None = None) -> None:
        """Move the cursor to row `index` of `area` (default: the area under the cursor)."""
        ...

    def start_edit(self, how: str, clear: bool = False) -> bool:
        """Edit the row under the cursor, as enter does (`clear`: start from an empty value), through
        the entry's own `start_edit`. False when the row can't be edited."""
        ...

    def begin_edit(self, editing: Editing) -> None:
        """Start typing into `editing`, an editor of the entry's own outside its rows (the repeat
        rate). Keeping it returns to `editing.back`, by default where the cursor was."""
        ...

    def push_undo(self, entry: UndoEntry) -> None:
        """One step u undoes: u calls `entry.revert(nav)` and logs what it returns."""
        ...

    def drop_undo(self, gone: Callable[[UndoEntry], bool]) -> None:
        """Forget the undo steps `gone` picks (a change that can't be undone any more)."""
        ...

    def open_entity(self, kind: str, name: str, how: str) -> None:
        """Open (or go to) the tab of another entity, at its area pick, and log it."""
        ...

    def copy(self, register: 'Register') -> None:
        """y copied `register`: p pastes it into an editor of the same type, in any tab."""
        ...

    def show(self, overlay: 'Helper') -> None:
        """Open `overlay` on top (a field helper); it has the keys until it closes. The entry logs it."""
        ...

    def close_overlay(self) -> None:
        """Close the overlay without a log line; the entry logs what it did (a helper applied)."""
        ...


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

    def on_open(self, nav: 'Host') -> None:
        """Its tab was opened or gone to."""

    def on_close(self, nav: 'Host') -> list[str]:
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

    def activate_row(self, nav: 'Host', area: Area, row: int, how: str) -> bool:
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

    def tick(self, nav: 'Host') -> bool:
        """The clock ticked: take in what arrived (an echo's messages). True when the views should redraw."""
        return False

    def verbs(self) -> dict[str, Verb]:
        """The verbs this entry offers now, by name: primary, secondary, repeat, rate, set_rate,
        helper, helper_apply, history_older, history_newer, yank, paste, and on field rows fold,
        unfold, add_item, delete_item. NavState says a verb missing here isn't available."""
        return {}
