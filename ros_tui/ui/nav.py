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

"""The navigation model of the UI: tabs, layers, cursors, overlays and the `g` prefix.

Pure Python (no textual, no rclpy), ported from the design's state `S` and keydown handler
(docs/design/hybrid-keys.html). Widgets render a `NavState` and hand it every key through
`handle_key`; `keymap.KEYMAP` says which action a key runs. What an entry holds (its rows, values
and verbs) comes from an `EntryProvider`, so the topic, service, action and node entries plug in
without the model knowing about them.

The layers, top to bottom: TABS (the tab row) › IN (inside a tab: the ☰ list, or an entry's area
pick) › AREA (the rows of one area) › EDIT (insert: typing into one value). esc goes up one, enter
goes down one.

Time comes only from `NavState.clock`: the bridge's `now()` in the app (FakeBridge's ManualClock in
tests), and a clock that stands still otherwise. `tick()` expires what is timed, such as the toast.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, NamedTuple

from ros_tui.constants import NAV_ACTIVITY_MAX, NAV_ERRLINE_S, NAV_LOG_LINES, NAV_TOAST_S, PUBLISH_DEFAULT_RATE_HZ
from ros_tui.ui import keymap
from ros_tui.ui.helpers import Helper
from ros_tui.ui.keymap import COMMANDS, MAX_SUGGESTIONS, key_char, key_display, normalize_key

TABS, IN, AREA, EDIT = LAYERS = ('tabs', 'in', 'area', 'edit')
KINDS = ('topics', 'services', 'actions', 'nodes')
CLOSE = 'close'  # UndoEntry kind of a closed tab; NavState undoes it itself.
ANYWHERE = '*'  # UndoEntry owner that any tab can undo (only a closed tab).
NOTHING_TO_UNDO = 'nothing to undo here'


@dataclass(frozen=True)
class CatalogItem:
    name: str
    type: str
    publishers: int = 0  # Topics only: decides whether a topic opens in Echo or Publish.


@dataclass(frozen=True)
class Tab:
    kind: str  # One of KINDS.
    name: str

    @property
    def key(self) -> str:
        """The entry key ('topics:/chatter') that per-entry state is stored under."""
        return f'{self.kind}:{self.name}'

    @staticmethod
    def of(key: str) -> 'Tab':
        """The tab of an entry key ('topics:/chatter'), e.g. an UndoEntry's owner."""
        return Tab(*key.split(':', 1))


@dataclass(frozen=True)
class Area:
    """One panel of an entry. Ids follow the design: msg, out, ifs, par (and rate for its editor)."""

    id: str
    title: str  # In capitals; the breadcrumb shows it in lower case.
    enter: str = ''  # Footer "enter …" label inside the area ('' when enter does nothing there).
    editable: bool = False  # i / a / c and enter edit its rows.


# The areas of each screen, as AREAS in the design. A topic's screen depends on its mode.
AREAS = {
    'topics:echo': (Area('out', 'LATEST MESSAGE', 'show / hide field'),),
    'topics:publish': (Area('msg', 'MESSAGE', 'edit', True),),
    'services': (Area('msg', 'REQUEST', 'edit', True), Area('out', 'RESPONSE')),
    'actions': (Area('msg', 'GOAL', 'edit', True), Area('out', 'RESULT')),
    'nodes': (Area('ifs', 'INTERFACES', 'open it'), Area('par', 'PARAMETERS', 'edit', True)),
}


@dataclass
class Editing:
    """The value being typed in the EDIT layer."""

    area: str  # The area id it belongs to ('rate' for the repeat-rate editor).
    row: int
    value: str
    old: str = ''
    fresh: bool = False  # The first typed character replaces the value instead of appending.
    field: str = ''  # The field as the user sees it, for log lines.
    note: str = '(insert)'  # Appended to the "edit <field>" log line.
    crumb: tuple[str, ...] = ()  # Breadcrumb parts instead of the area title, e.g. ('repeat rate',).
    back: str = AREA  # The layer to return to when the edit ends.


@dataclass(frozen=True)
class UndoEntry:
    owner: str  # The tab key it was made in, or ANYWHERE.
    kind: str  # CLOSE, or whatever the provider that pushed it understands ('edit', 'rate', …).
    data: Any = None


@dataclass(frozen=True)
class Commit:
    """A provider's answer to committing an edit: kept (with a log line), or an error message."""

    ok: bool
    text: str
    undo: UndoEntry | None = None
    activity: tuple[str, str] = ()  # (text, cls) of an activity line it causes, e.g. a running repeat's new rate.


@dataclass
class Search:
    q: str = ''
    cur: int = 0


@dataclass
class CommandLine:
    q: str = ''
    cur: int = 0
    moved: bool = False  # ↑↓ picked a suggestion, so enter runs it rather than the typed text.


@dataclass
class LogView:
    cur: int = 0


@dataclass(frozen=True)
class Toast:
    text: str
    kind: str = ''  # '', 'ok', 'info' or 'bad'.
    until: float = 0.0  # Clock time it goes away at.


class Errline(NamedTuple):
    text: str  # A bad value's message, shown under the entry's panel.
    until: float  # Clock time it goes away at.


@dataclass(frozen=True)
class ActivityLine:
    kind: str  # The entry's kind ('' for none) and name, so :log can jump there.
    name: str
    text: str
    cls: str = ''


class Running(NamedTuple):
    """Something an entry has running, as the tab row, the top bar and the Here column show it."""

    glyph: str  # '◉' an echo, '↻' a repeating publish, a frame of the '◐◓◑◒' spinner for a goal executing.
    label: str  # The Here column's words: 'echoing', '10 Hz', 'running'.
    tone: str  # The theme token it is drawn in: 'live' or 'ok'.


class Footer(NamedTuple):
    mode: str  # normal, insert, helper, search or command.
    path: tuple[str, ...]  # The breadcrumb; the last part is where you are.
    esc: str  # What esc does here ('' when nothing, or hidden by search / which-key).
    enter: str
    pending: str  # A pending prefix ('g'), shown as "g…".
    helper: str  # 'Quaternion' when the row under the cursor has a helper, else ''.


class EntryProvider:
    """What an entry holds and does. NavState asks; later steps subclass this per entry kind.

    The default gives every entry the design's areas, no rows and no verbs, and switches a topic
    between Echo and Publish. Hooks that take `nav` may change it (log, toast, push undo, open a
    tab); the others only answer.
    """

    def __init__(self):
        self._modes: dict[str, str] = {}

    def for_tab(self, tab: Tab) -> 'EntryProvider':
        """The provider that holds this tab's entry: itself, unless it routes by kind
        (entries.EntryRouter). Views use it to reach an entry kind's own data, such as a node's
        parameters."""
        return self

    def on_open(self, nav: 'NavState', tab: Tab) -> None:
        """A tab was opened or gone to. A topic opens in Echo when someone publishes it."""
        if tab.kind == 'topics' and tab.name not in self._modes:
            item = nav.item(tab)
            self._modes[tab.name] = 'echo' if item and item.publishers > 0 else 'publish'

    def mode(self, tab: Tab) -> str | None:
        """A topic's 'echo' or 'publish'; None for the other kinds."""
        return self._modes.get(tab.name) if tab.kind == 'topics' else None

    def screen(self, tab: Tab) -> str:
        """The key the area pick is remembered under, and that AREAS is indexed by."""
        mode = self.mode(tab)
        return f'{tab.kind}:{mode}' if mode else tab.kind

    def areas(self, tab: Tab) -> tuple[Area, ...]:
        return AREAS.get(self.screen(tab), ())

    def row_count(self, tab: Tab, area: Area) -> int:
        return 0

    def start_edit(self, tab: Tab, area: Area, row: int, clear: bool) -> Editing | None:
        """An Editing for the row, or None when it can't be edited."""
        return None

    def commit_edit(self, tab: Tab, editing: Editing) -> Commit:
        return Commit(True, f'kept {editing.field or "the value"}')

    def activate_row(self, nav: 'NavState', tab: Tab, area: Area, row: int, how: str) -> bool:
        """enter on a row, before it is edited: open an interface, show / hide a field, fold or
        unfold a nested message or list. True if done (then the row isn't edited)."""
        return False

    def leave_area(self, tab: Tab, area: Area) -> str | None:
        """esc out of an area: a log line instead of "up one layer" (e.g. a frozen echo goes live)."""
        return None

    def esc_label(self, tab: Tab, area: Area) -> str | None:
        """The footer's esc label inside an area, when it isn't the default ('go live')."""
        return None

    def enter_label(self, tab: Tab, area: Area, row: int) -> str | None:
        """The footer's enter label on a row, when it isn't the area's ('unfold' on a folded row)."""
        return None

    def helper_name(self, tab: Tab, area: Area, row: int) -> str | None:
        """'Quaternion' when the row has a field helper."""
        return None

    def label_vars(self, tab: Tab | None) -> dict[str, Any]:
        """Values for keymap labels, e.g. the repeat rate in "repeat at {rate} Hz"."""
        return {'rate': f'{PUBLISH_DEFAULT_RATE_HZ:g}'}

    def running(self) -> dict[Tab, tuple[Running, ...]]:
        """What runs in this provider's entries (echoes, repeats, goals), by entry, open or not."""
        return {}

    def tick(self, nav: 'NavState') -> bool:
        """The clock ticked: take in what arrived (an echo's messages). True when the views should redraw."""
        return False

    def verb(self, nav: 'NavState', tab: Tab | None, name: str, how: str, arg: Any = None) -> bool:
        """Run an entry verb: primary, secondary, repeat, rate, set_rate, toggle_mode, helper,
        helper_apply, helper_key, history_older, history_newer, yank, paste, and on field rows fold,
        unfold, add_item, delete_item. True if handled."""
        if name == 'toggle_mode':
            return self._toggle_mode(nav, tab, how, arg)
        if name == 'helper':
            nav.show_toast('no helper for this field — fields with one show [f …]', 'bad')
            nav.log_line(how, 'no helper on this field')
            return True
        if name in ('repeat', 'rate', 'set_rate') and (tab is None or tab.kind != 'topics'):
            nav.log_line(how, 'repeating is for topics')
            if name == 'set_rate':
                nav.show_toast(':rate works in a topic tab', 'bad')
            return True
        return False

    def undo(self, nav: 'NavState', entry: UndoEntry) -> str:
        """Undo a change this provider pushed; returns the log line."""
        return 'undid it'

    def _toggle_mode(self, nav, tab, how, to):
        if tab is None or tab.kind != 'topics':
            nav.log_line(how, 'only topics have Echo / Publish')
            return True
        if nav.layer == EDIT:
            nav.commit_edit(how)
        self._modes[tab.name] = to or ('publish' if self._modes.get(tab.name) == 'echo' else 'echo')
        nav.layer = IN
        nav.log_line(how, f'now in {self._modes[tab.name]}')
        return True


class Press(NamedTuple):
    key: str  # Canonical (keymap.normalize_key).
    char: str | None  # What it types, if anything.
    how: str  # How it reads in the log: 'esc', '^s', 'j'.


@dataclass
class NavState:
    provider: EntryProvider = field(default_factory=EntryProvider)
    clock: Callable[[], float] = lambda: 0.0  # Seconds; the app passes the bridge's now().
    catalog: dict[str, list[CatalogItem]] = field(default_factory=lambda: {kind: [] for kind in KINDS})
    tabs: list[Tab] = field(default_factory=list)
    active: int = -1  # -1 is the ☰ list (tab 0).
    layer: str = IN
    tab_cur: int = -1  # The cursor on the tab row (layer TABS).
    chip: int = -1  # The kind filter on the ☰ list: -1 all, else an index into KINDS.
    list_cur: int = 0
    area_idx: dict[tuple[str, str], int] = field(default_factory=dict)  # (entry key, screen) -> area.
    row_idx: dict[tuple[str, str], int] = field(default_factory=dict)  # (entry key, area id) -> row.
    editing: Editing | None = None
    search: Search | None = None
    cmd: CommandLine | None = None
    logv: LogView | None = None
    helper: Helper | None = None
    which_key: str | None = None  # 'all' (the ? popup), 'g' (the prefix popup) or None.
    pending: str = ''  # A typed prefix waiting for its next key ('g').
    undo_stack: list[UndoEntry] = field(default_factory=list)
    errlines: dict[str, Errline] = field(default_factory=dict)  # Entry key -> its current error line.
    log: list[tuple[str, str]] = field(default_factory=list)  # (key, what happened), newest first.
    toast: Toast | None = None
    activity: list[ActivityLine] = field(default_factory=list)  # Newest first.
    quit: bool = False  # :q asked to leave; the app acts on it.

    # ---------- the catalogue ----------
    def set_catalog(self, graph: Any, publishers: Mapping[str, int] | None = None) -> None:
        """Feed the ☰ list from a GraphSnapshot (or anything with topics / services / actions / nodes
        of entries with a name and `types` or `type`). `publishers` counts a topic's publishers."""
        publishers = publishers or {}
        for kind in KINDS:
            self.catalog[kind] = [
                CatalogItem(entry.name, _type_of(kind, entry), publishers.get(entry.name, getattr(entry, 'publishers', 0)))
                for entry in getattr(graph, kind, ())]
        self.list_cur = _clamp(self.list_cur, len(self.home_rows()) - 1)

    def item(self, tab: Tab) -> CatalogItem | None:
        return next((i for i in self.catalog.get(tab.kind, ()) if i.name == tab.name), None)

    def home_rows(self) -> list[tuple[str, CatalogItem]]:
        """The ☰ list: (kind, item), grouped by kind, filtered by the chip."""
        kinds = KINDS if self.chip < 0 else (KINDS[self.chip],)
        return [(kind, item) for kind in kinds for item in self.catalog[kind]]

    def is_open(self, kind: str, name: str) -> bool:
        return Tab(kind, name) in self.tabs

    def search_rows(self) -> list[tuple[str, CatalogItem]]:
        q = self.search.q.lower() if self.search else ''
        return [(kind, item) for kind in KINDS for item in self.catalog[kind]
                if not q or q in item.name.lower() or q in item.type.lower()]

    # ---------- where we are ----------
    @property
    def tab(self) -> Tab | None:
        return self.tabs[self.active] if 0 <= self.active < len(self.tabs) else None

    def entry_mode(self) -> str | None:
        return self.provider.mode(self.tab) if self.tab else None

    def areas(self) -> tuple[Area, ...]:
        return self.provider.areas(self.tab) if self.tab else ()

    def area_index(self) -> int:
        areas = self.areas()
        if not areas:
            return 0
        return min(self.area_idx.get((self.tab.key, self.provider.screen(self.tab)), 0), len(areas) - 1)

    def area(self) -> Area | None:
        areas = self.areas()
        return areas[self.area_index()] if areas else None

    def set_area(self, index: int) -> None:
        self.area_idx[(self.tab.key, self.provider.screen(self.tab))] = index

    def row_count(self, area: Area | None = None) -> int:
        area = area or self.area()
        return self.provider.row_count(self.tab, area) if self.tab and area else 0

    def row_index(self, area: Area | None = None) -> int:
        """The current row of the area, kept within its rows (they can change when the bridge answers)."""
        area = area or self.area()
        if not self.tab or not area:
            return 0
        return _clamp(self.row_idx.get((self.tab.key, area.id), 0), self.row_count(area) - 1)

    def set_row(self, index: int, area: Area | None = None) -> None:
        area = area or self.area()
        self.row_idx[(self.tab.key, area.id)] = index

    def running(self, kind: str, name: str) -> tuple[Running, ...]:
        """What the entry has running (◉ echoing, ↻ 10 Hz), for its tab, list row and search row."""
        return self.provider.running().get(Tab(kind, name), ())

    def running_all(self) -> list[tuple[Tab, Running]]:
        """Everything running, for the top bar."""
        return [(tab, marker) for tab, markers in self.provider.running().items() for marker in markers]

    def helper_name(self) -> str | None:
        """The helper of the field under the cursor (message areas only), as the design's helperAt()."""
        area = self.area()
        if self.layer == TABS or area is None or area.id != 'msg':
            return None
        return self.provider.helper_name(self.tab, area, self.row_index(area))

    def label_vars(self) -> dict[str, Any]:
        return {'rate': '', 'helper': self.helper_name() or '', 'jump': self.helper.jump_keys() if self.helper else '',
                **self.provider.label_vars(self.tab)}

    def list_mode(self) -> str:
        """The keymap mode whose keys "Keys right now" lists: the topmost overlay, insert or normal."""
        if self.helper:
            return 'helper'
        if self.cmd:
            return 'command'
        if self.logv:
            return 'activity'
        if self.search:
            return 'search'
        return 'insert' if self.layer == EDIT else 'normal'

    def input_mode(self) -> str:
        """The keymap mode that gets the next key: the popups (? and g…) sit on top of list_mode."""
        if self.which_key == 'all':
            return 'whichkey'
        mode = self.list_mode()
        return 'g' if mode == 'normal' and self.pending == 'g' else mode

    # ---------- the footer ----------
    def mode_name(self) -> str:
        """The footer's mode badge: the :log view keeps NORMAL."""
        mode = self.list_mode()
        return 'normal' if mode == 'activity' else mode

    def path(self) -> tuple[str, ...]:
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

    def esc_label(self) -> str:
        if self.helper:
            return 'cancel'
        if self.logv:
            return 'close'
        if self.layer == AREA and self.tab:
            label = self.provider.esc_label(self.tab, self.area())
            return label or ('pick another area' if len(self.areas()) > 1 else 'back out')
        return {EDIT: 'keep it', IN: 'tab row', TABS: ''}[self.layer]

    def enter_label(self) -> str:
        if self.helper:
            return 'apply'
        if self.logv:
            return 'go there'
        if self.layer == TABS:
            return 'go in'
        if self.layer == IN:
            if not self.tab:
                rows = self.home_rows()
                return f'open {rows[self.list_cur][1].name}' if 0 <= self.list_cur < len(rows) else ''
            area = self.area()
            return f'into {area.title.lower()}' if area else ''
        if self.layer == AREA:
            area = self.area()
            if area is None:
                return ''
            return self.provider.enter_label(self.tab, area, self.row_index(area)) or area.enter
        return 'keep it'

    def footer(self) -> Footer:
        hide = self.search is not None or self.which_key == 'all'
        helper = self.helper_name() if not (hide or self.helper or self.logv or self.layer == EDIT) else None
        return Footer(self.mode_name(), self.path(), '' if hide else self.esc_label(),
                      '' if hide else self.enter_label(), self.pending, helper or '')

    def summary(self) -> dict[str, Any]:
        """Plain data for the harness's state JSON and for tests."""
        foot = self.footer()
        return {
            'layer': self.layer, 'mode': foot.mode, 'path': list(foot.path), 'esc': foot.esc,
            'enter': foot.enter, 'pending': foot.pending, 'active': self.active, 'tab_cur': self.tab_cur,
            'tabs': [tab.name for tab in self.tabs], 'chip': self.chip, 'list_cur': self.list_cur,
            'area': self.area().id if self.tab and self.area() else None,
            'row': self.row_index() if self.tab else None,
            'search': self.search.q if self.search else None, 'cmd': self.cmd.q if self.cmd else None,
            'which_key': self.which_key, 'log': self.log[0] if self.log else None,
            'toast': [self.toast.text, self.toast.kind] if self.toast else None,
        }

    # ---------- feedback ----------
    def log_line(self, how: str, what: str) -> None:
        self.log.insert(0, (how, what))
        del self.log[NAV_LOG_LINES:]

    def show_toast(self, text: str, kind: str = '') -> None:
        self.toast = Toast(text, kind, self.clock() + NAV_TOAST_S)

    def errline(self, tab: Tab) -> str:
        line = self.errlines.get(tab.key)
        return line.text if line else ''

    def report_error(self, tab: Tab, message: str) -> None:
        """A bad value or a blocked send (the design's inl): an errline under the entry's panel and a
        red activity line."""
        self.errlines[tab.key] = Errline(message, self.clock() + NAV_ERRLINE_S)
        self.add_activity(tab, f'✗ {message}', 'r')

    def tick(self) -> bool:
        """Let the entries take in what arrived (echoes), and expire what is timed (the toast,
        errlines). True when something changed, so the views redraw."""
        changed = self.provider.tick(self)
        now = self.clock()
        expired = [key for key, line in self.errlines.items() if now >= line.until]
        for key in expired:
            del self.errlines[key]
        if self.toast and now >= self.toast.until:
            self.toast = None
            changed = True
        return changed or bool(expired)

    def add_activity(self, tab: Tab | None, text: str, cls: str = '') -> None:
        self.activity.insert(0, ActivityLine(tab.kind if tab else '', tab.name if tab else '', text, cls))
        del self.activity[NAV_ACTIVITY_MAX:]

    def hint(self, how: str) -> None:
        self.log_line(how, f'nothing on "{how}" here — ? shows the keys')

    # ---------- the key router ----------
    def handle_key(self, key: str) -> bool:
        """Route one key (a textual key name or a character). False when nothing wanted it."""
        key = normalize_key(key)
        mode = self.input_mode()
        how = key_display(key)
        if mode == 'g':  # The key after g resolves the prefix, whatever it is.
            self.pending = ''
            self.which_key = None
            how = 'g' + how
        press = Press(key, key_char(key), how)
        action = keymap.lookup(self, mode, key)
        if action:
            ACTIONS[action](self, press)
            return True
        if mode == 'g':
            self.log_line(how, 'no such key')
            return True
        if mode != 'normal':
            return True  # Overlays and insert are modal: they swallow what they don't use.
        if press.char is None:
            return False
        if self.layer != TABS:
            self.hint(press.how)
        return True

    # ---------- tabs ----------
    def activate(self, index: int, how: str, quiet: bool = False) -> None:
        self.active = index
        self.layer = IN
        self.editing = None
        if not quiet:
            self.log_line(how, '☰ the list' if index < 0 else f'tab {index + 1}: {self.tabs[index].name}')

    def open_entity(self, kind: str, name: str, how: str) -> None:
        tab = Tab(kind, name)
        is_new = tab not in self.tabs
        if is_new:
            self.tabs.append(tab)
        index = self.tabs.index(tab)
        self.provider.on_open(self, tab)
        self.search = None
        self.active = index
        self.layer = IN
        self.editing = None
        self.log_line(how, f'{"opened" if is_new else "went to"} {name} (tab {index + 1})')

    def close_tab(self, index: int, how: str) -> None:
        if index < 0:
            self.log_line(how, 'the ☰ list always stays')
            return
        tab = self.tabs.pop(index)
        self.undo_stack.append(UndoEntry(ANYWHERE, CLOSE, (tab, index)))
        if self.active == index:
            self.active = min(index, len(self.tabs) - 1)
        elif self.active > index:
            self.active -= 1
        if self.layer == TABS:
            self.tab_cur = min(index, len(self.tabs) - 1)
        else:
            self.layer = IN
        self.editing = None
        self.log_line(how, f'closed {tab.name} — u reopens it')
        self.show_toast(f'closed {tab.name} · u undoes', 'info')

    def step_tab(self, delta: int, how: str) -> None:
        """H / L, gT / gt: the previous / next tab, wrapping through the ☰ list."""
        self.activate(_cycle(self.active, delta, len(self.tabs)), how)

    def goto_tab(self, digit: str) -> None:
        if digit == '0':
            self.activate(-1, digit)
        elif int(digit) <= len(self.tabs):
            self.activate(int(digit) - 1, digit)
        else:
            self.log_line(digit, f'no tab {digit}')

    # ---------- undo ----------
    def push_undo(self, entry: UndoEntry) -> None:
        self.undo_stack.append(entry)

    def undo(self, how: str) -> None:
        """Undo your last change in this entry, or reopen the tab you just closed: a closed tab has
        no tab of its own to undo from, so any tab can reopen it."""
        here = self.tab.key if self.tab else 'home'
        index = next((i for i in range(len(self.undo_stack) - 1, -1, -1)
                      if self.undo_stack[i].owner in (ANYWHERE, here)), -1)
        if index < 0:
            self.log_line(how, NOTHING_TO_UNDO)
            self.show_toast(NOTHING_TO_UNDO, 'info')
            return
        entry = self.undo_stack.pop(index)
        if entry.kind != CLOSE:
            self.log_line(how, self.provider.undo(self, entry))
            return
        tab, at = entry.data
        if tab in self.tabs:
            self.active = self.tabs.index(tab)
        else:
            at = min(at, len(self.tabs))
            self.tabs.insert(at, tab)
            self.active = at
        self.layer = IN
        self.log_line(how, f'reopened {tab.name}')

    # ---------- layers ----------
    def go_up(self, how: str) -> None:
        if self.layer == EDIT:
            self.commit_edit(how)
        elif self.layer == AREA:
            self.layer = IN
            self.log_line(how, self.provider.leave_area(self.tab, self.area()) or 'up one layer')
        elif self.layer == IN:
            self.layer = TABS
            self.tab_cur = self.active
            self.log_line(how, 'up to the tab row')
        else:
            self.log_line(how, 'top layer — :q quits')

    def go_down(self, how: str) -> None:
        if self.layer == TABS:
            self.activate(self.tab_cur, how)
        elif self.layer == IN:
            if not self.tab:
                rows = self.home_rows()
                if 0 <= self.list_cur < len(rows):
                    self.open_entity(rows[self.list_cur][0], rows[self.list_cur][1].name, how)
                return
            area = self.area()
            if area is None:
                self.log_line(how, 'nothing inside this tab yet')
                return
            self.layer = AREA
            self.log_line(how, f'inside {area.title.lower()}')
        elif self.layer == AREA:
            self.activate_row(how)
        else:
            self.commit_edit(how)

    def activate_row(self, how: str) -> None:
        """enter on a row: the entry's own action first (fold a list, open an interface), else edit it."""
        if self.provider.activate_row(self, self.tab, self.area(), self.row_index(), how):
            return
        if not self.start_edit(how):
            self.log_line(how, 'nothing to edit here — esc goes back up')

    # ---------- insert ----------
    def start_edit(self, how: str, clear: bool = False) -> bool:
        """Edit the row under the cursor (the AREA layer). False when the row isn't editable."""
        area = self.area()
        if self.tab is None or area is None:
            return False
        editing = self.provider.start_edit(self.tab, area, self.row_index(area), clear)
        if editing is None:
            return False
        self.editing = editing
        self.layer = EDIT
        self.log_line(how, f'{"clear and edit" if clear else "edit"} {editing.field} {editing.note}')
        return True

    def commit_edit(self, how: str) -> bool:
        """Keep the typed value. On a bad value, esc drops it (keeping the old one) and anything else
        stays in insert with an error line. True when the edit ended."""
        editing = self.editing
        if editing is None:
            return True
        result = self.provider.commit_edit(self.tab, editing)
        if not result.ok:
            return self._bad_value(how, result.text)
        if result.undo:
            self.push_undo(result.undo)
        if result.activity:
            self.add_activity(self.tab, *result.activity)
        self.errlines.pop(self.tab.key, None)
        self.log_line(how, result.text)
        self.editing = None
        self.layer = editing.back
        return True

    def _bad_value(self, how: str, message: str) -> bool:
        if how == 'esc':
            self.log_line(how, f'✗ {message} — dropped, kept the old value')
            self.show_toast(f'{message} — kept the old value', 'bad')
            self.errlines.pop(self.tab.key, None)
            self.layer = self.editing.back
            self.editing = None
            return True
        self.log_line(how, f'✗ {message} — still editing (esc drops it)')
        self.report_error(self.tab, message)
        return False

    def edit_step(self, how: str, delta: int) -> None:
        """tab / shift+tab in insert: keep the value and edit the next / previous field, skipping
        rows that aren't edited (a folded message). Past the last one it edits the same field again."""
        row = self.editing.row
        if not self.commit_edit(how):
            return
        last = self.row_count() - 1
        for index in range(row + delta, last + 1 if delta > 0 else -1, delta):
            self.set_row(index)
            if self.start_edit(how):
                return
        self.set_row(_clamp(row, last))
        self.start_edit(how)

    def type_char(self, char: str) -> None:
        if self.editing.fresh:
            self.editing.value = ''
            self.editing.fresh = False
        self.editing.value += char

    def backspace(self) -> None:
        self.editing.value = '' if self.editing.fresh else self.editing.value[:-1]
        self.editing.fresh = False

    # ---------- verbs ----------
    def verb(self, name: str, how: str, arg: Any = None) -> None:
        if self.tab is None and name in ('yank', 'paste'):
            self.log_line(how, 'open an entry first')
            return
        if not self.provider.verb(self, self.tab, name, how, arg):
            self.log_line(how, 'not built yet')

    def primary(self, how: str) -> None:
        """space / ^s: the entry's one sending verb. In insert it keeps the value first."""
        if self.tab is None:
            return
        if self.layer == EDIT and not self.commit_edit(how):
            return
        self.verb('primary', how)

    def open_helper(self, how: str) -> None:
        area = self.area()
        if self.layer == IN and area and area.id == 'msg':
            self.layer = AREA
        self.verb('helper', how)

    # ---------- moving ----------
    def move_top(self, how: str) -> None:
        if self.layer == IN and not self.tab:
            self.list_cur = 0
        elif self.layer == AREA:
            self.set_row(0)
        elif self.layer == TABS:
            self.tab_cur = -1
        self.log_line(how, 'to the top')

    def move_bottom(self, how: str) -> None:
        if self.layer == IN and not self.tab:
            self.list_cur = max(0, len(self.home_rows()) - 1)
        elif self.layer == AREA:
            self.set_row(max(0, self.row_count() - 1))
        elif self.layer == TABS:
            self.tab_cur = len(self.tabs) - 1
        self.log_line(how, 'to the bottom')

    def step_tab_cursor(self, delta: int) -> None:
        """h / l on the tab row: wraps from the last tab to ☰ and back."""
        self.tab_cur = _cycle(self.tab_cur, delta, len(self.tabs))

    def step_list(self, delta: int) -> None:
        self.list_cur = _clamp(self.list_cur + delta, len(self.home_rows()) - 1)

    def step_chip(self, delta: int, how: str) -> None:
        """tab / shift+tab on the ☰ list: all › topics › services › actions › nodes › all."""
        self.chip = _cycle(self.chip, delta, len(KINDS))
        self.list_cur = 0
        self.log_line(how, f'showing {"everything" if self.chip < 0 else KINDS[self.chip]}')

    def step_area(self, delta: int) -> None:
        count = len(self.areas())
        if count:
            self.set_area((self.area_index() + delta) % count)

    def step_row(self, delta: int) -> None:
        count = self.row_count()
        if count:
            self.set_row(_clamp(self.row_index() + delta, count - 1))

    def edit_row(self, how: str, clear: bool = False) -> None:
        """i / a / c: edit the row under the cursor. From the area pick (IN) they go into the area first."""
        back = self.layer
        self.layer = AREA
        if not self.start_edit(how, clear):
            self.layer = back
            self.hint(how)

    # ---------- search ----------
    def search_open(self, how: str) -> None:
        self.search = Search()
        self.log_line(how, 'search everything')

    def search_close(self) -> None:
        self.search = None
        self.log_line('esc', 'search closed — back where you were')

    def search_step(self, delta: int) -> None:
        self.search.cur = _clamp(self.search.cur + delta, len(self.search_rows()) - 1)

    def search_enter(self, how: str) -> None:
        rows = self.search_rows()
        if 0 <= self.search.cur < len(rows):
            kind, item = rows[self.search.cur]
            self.open_entity(kind, item.name, how)

    def search_edit(self, text: str) -> None:
        self.search.q = text
        self.search.cur = 0

    # ---------- command line ----------
    def cmd_suggestions(self) -> list[tuple[str, str]]:
        """The design's cmdSuggest(): prefix matches, or the one command once an argument is typed."""
        q = self.cmd.q.lstrip() if self.cmd else ''
        word = q.split(' ')[0]
        return [c for c in COMMANDS if not q or (c[0].strip() == word if ' ' in q else c[0].startswith(word))
                ][:MAX_SUGGESTIONS]

    def _cmd_clamp(self) -> list[tuple[str, str]]:
        suggestions = self.cmd_suggestions()
        self.cmd.cur = min(self.cmd.cur, max(0, len(suggestions) - 1))
        return suggestions

    def cmd_edit(self, text: str) -> None:
        self.cmd.q = text
        self.cmd.cur = 0
        self.cmd.moved = False

    def cmd_backspace(self) -> None:
        """Backspace on an empty command line closes it."""
        if self.cmd.q:
            self.cmd_edit(self.cmd.q[:-1])
        else:
            self.cmd = None

    def cmd_complete(self) -> None:
        suggestions = self._cmd_clamp()
        if ' ' not in self.cmd.q and suggestions:
            self.cmd_edit(suggestions[self.cmd.cur][0])

    def cmd_move(self, delta: int) -> None:
        suggestions = self._cmd_clamp()
        if suggestions:
            self.cmd.cur = (self.cmd.cur + delta) % len(suggestions)
            self.cmd.moved = True

    def cmd_enter(self) -> None:
        """enter runs the typed command, or the picked suggestion for a partial word ('se' runs
        services) or picked with ↑↓. A command that takes an argument stays open for it."""
        suggestions = self._cmd_clamp()
        q = self.cmd.q
        word = q.strip().split(' ')[0]
        partial = q.strip() and not any(c[0].strip() == word for c in COMMANDS)
        if suggestions and ' ' not in q and (self.cmd.moved or partial):
            q = suggestions[self.cmd.cur][0]
        self.cmd = None
        if q.endswith(' '):
            self.cmd = CommandLine(q)
            return
        self.run_command(q)

    def run_command(self, text: str) -> None:
        if not text.strip():
            return
        name, *rest = text.split()
        arg = ' '.join(rest)
        how = ':' + name
        if name in KINDS or name == 'all':
            self.chip = KINDS.index(name) if name in KINDS else -1
            self.list_cur = 0
            self.activate(-1, how, quiet=True)
            self.log_line(how, f'☰ lists {"everything" if name == "all" else name}')
        elif name == 'rate':
            self.verb('set_rate', how, arg)
        elif name in ('echo', 'pub'):
            self.verb('toggle_mode', how, 'echo' if name == 'echo' else 'publish')
        elif name == 'close':
            self.close_tab(self.active, how)
        elif name == 'help':
            self.which_key = 'all'
            self.log_line(how, 'showing the keys')
        elif name in ('log', 'messages'):
            self.logv = LogView()
            self.log_line(':log', 'all activity')
        elif name in ('q', 'quit'):
            self.quit = True
            self.log_line(':q', 'quit')
        else:
            self.show_toast(f'unknown command :{name} — : then tab lists them', 'bad')
            self.log_line(how, 'unknown command')

    # ---------- popups ----------
    def g_prefix(self) -> None:
        self.pending = 'g'
        self.which_key = 'g'

    def helper_close(self) -> None:
        self.helper = None
        self.log_line('esc', 'helper closed, nothing changed')

    # ---------- activity log ----------
    def log_goto(self, index: int) -> None:
        self.logv.cur = _clamp(index, len(self.activity) - 1)

    def log_enter(self) -> None:
        line = self.activity[self.logv.cur] if self.logv.cur < len(self.activity) else None
        self.logv = None
        if line and line.kind:
            self.open_entity(line.kind, line.name, 'enter')


def _clamp(index: int, last: int) -> int:
    """`index` kept in 0..last (0 when there is nothing)."""
    return max(0, min(last, index))


def _cycle(index: int, delta: int, count: int) -> int:
    """Step an index in -1..count-1 (-1 being ☰ or "all"), wrapping at both ends."""
    return (index + 1 + delta) % (count + 1) - 1


def short_type(kind: str, type_name: str) -> str:
    """The type as search results show it: 'String' for std_msgs/msg/String, 'node' for a node."""
    return 'node' if kind == 'nodes' else type_name.rsplit('/', 1)[-1]


def _type_of(kind: str, entry: Any) -> str:
    """The type shown and searched: a GraphSnapshot node's types[0] is its namespace ('namespace /')."""
    if hasattr(entry, 'type'):
        return entry.type
    types = getattr(entry, 'types', ())
    if kind == 'nodes':
        return f'namespace {types[0] if types else "/"}'
    return types[0] if types else ''


def _set(name: str, value: Any) -> Callable[[NavState, Press], None]:
    return lambda nav, press: setattr(nav, name, value)


# keymap action name -> what it does. Every action in keymap.KEYMAP is here, and nothing else (test_keymap).
ACTIONS: dict[str, Callable[[NavState, Press], None]] = {
    # popups
    'which_key': _set('which_key', 'all'),
    'which_key_close': _set('which_key', None),
    'g_prefix': lambda nav, p: nav.g_prefix(),
    'g_cancel': lambda nav, p: nav.log_line('esc', 'g canceled'),
    # field helper: the entry opens it, hands it its keys and writes its value (entries/message.py)
    'helper_key': lambda nav, p: nav.verb('helper_key', p.how, p.key),
    'helper_apply': lambda nav, p: nav.verb('helper_apply', p.how),
    'helper_close': lambda nav, p: nav.helper_close(),
    # command line
    'cmd_open': lambda nav, p: setattr(nav, 'cmd', CommandLine()),
    'cmd_type': lambda nav, p: nav.cmd_edit(nav.cmd.q + p.char),
    'cmd_back': lambda nav, p: nav.cmd_backspace(),
    'cmd_complete': lambda nav, p: nav.cmd_complete(),
    'cmd_up': lambda nav, p: nav.cmd_move(-1),
    'cmd_down': lambda nav, p: nav.cmd_move(1),
    'cmd_run': lambda nav, p: nav.cmd_enter(),
    'cmd_cancel': _set('cmd', None),
    # activity log
    'log_down': lambda nav, p: nav.log_goto(nav.logv.cur + 1),
    'log_up': lambda nav, p: nav.log_goto(nav.logv.cur - 1),
    'log_top': lambda nav, p: nav.log_goto(0),
    'log_bottom': lambda nav, p: nav.log_goto(len(nav.activity)),
    'log_enter': lambda nav, p: nav.log_enter(),
    'log_close': _set('logv', None),
    # search
    'search_open': lambda nav, p: nav.search_open(p.how),
    'search_type': lambda nav, p: nav.search_edit(nav.search.q + p.char),
    'search_back': lambda nav, p: nav.search_edit(nav.search.q[:-1]),
    'search_down': lambda nav, p: nav.search_step(1),
    'search_up': lambda nav, p: nav.search_step(-1),
    'search_enter': lambda nav, p: nav.search_enter(p.how),
    'search_close': lambda nav, p: nav.search_close(),
    # insert
    'edit_keep': lambda nav, p: nav.commit_edit(p.how),
    'edit_next': lambda nav, p: nav.edit_step(p.how, 1),
    'edit_prev': lambda nav, p: nav.edit_step(p.how, -1),
    'edit_back': lambda nav, p: nav.backspace(),
    'edit_type': lambda nav, p: nav.type_char(p.char),
    # layers
    'go_down': lambda nav, p: nav.go_down(p.how),
    'go_up': lambda nav, p: nav.go_up(p.how),
    # moving
    'move_top': lambda nav, p: nav.move_top(p.how),
    'move_bottom': lambda nav, p: nav.move_bottom(p.how),
    'tab_cursor_next': lambda nav, p: nav.step_tab_cursor(1),
    'tab_cursor_prev': lambda nav, p: nav.step_tab_cursor(-1),
    'list_down': lambda nav, p: nav.step_list(1),
    'list_up': lambda nav, p: nav.step_list(-1),
    'chip_next': lambda nav, p: nav.step_chip(1, p.how),
    'chip_prev': lambda nav, p: nav.step_chip(-1, p.how),
    'area_next': lambda nav, p: nav.step_area(1),
    'area_prev': lambda nav, p: nav.step_area(-1),
    'row_down': lambda nav, p: nav.step_row(1),
    'row_up': lambda nav, p: nav.step_row(-1),
    'edit': lambda nav, p: nav.edit_row(p.how),
    'clear': lambda nav, p: nav.edit_row(p.how, clear=True),
    # field rows (fields.py): fold / unfold, add / delete a list element
    'fold': lambda nav, p: nav.verb('fold', p.how),
    'unfold': lambda nav, p: nav.verb('unfold', p.how),
    'add_item': lambda nav, p: nav.verb('add_item', p.how),
    'delete_item': lambda nav, p: nav.verb('delete_item', p.how),
    # tabs
    'goto_tab': lambda nav, p: nav.goto_tab(p.key),
    'tab_next': lambda nav, p: nav.step_tab(1, p.how),
    'tab_prev': lambda nav, p: nav.step_tab(-1, p.how),
    'close': lambda nav, p: nav.close_tab(nav.tab_cur if nav.layer == TABS else nav.active, p.how),
    'undo': lambda nav, p: nav.undo(p.how),
    # verbs
    'primary': lambda nav, p: nav.primary(p.how),
    'secondary': lambda nav, p: nav.verb('secondary', p.how),
    'repeat': lambda nav, p: nav.verb('repeat', p.how),
    'rate': lambda nav, p: nav.verb('rate', p.how),
    'toggle_mode': lambda nav, p: nav.verb('toggle_mode', p.how),
    'helper': lambda nav, p: nav.open_helper(p.how),
    'history_older': lambda nav, p: nav.verb('history_older', p.how),
    'history_newer': lambda nav, p: nav.verb('history_newer', p.how),
    'yank': lambda nav, p: nav.verb('yank', p.how),
    'paste': lambda nav, p: nav.verb('paste', p.how),
}
