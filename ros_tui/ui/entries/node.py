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

"""The node entry: its INTERFACES (enter opens one in a tab) and PARAMETERS (edit, then space sets).

Pure Python (no textual, no rclpy), as the design's nodes branch: NODE_IF, nodeParams, the 'par'
branches of startEdit / commitEdit / undo, and setParams. A kept edit is a *change*: shown as
"new was old" and sent only by space / ^s (`set_node_parameter`, one call per changed
parameter). u undoes a change, in this tab only.

The node's interfaces and parameters are asked for when its tab is opened. The bridge answers on
its own thread; `post` brings each answer to the UI thread (the app posts a message) before it
touches the model. Until an answer is in, the area says "loading…".
"""

import re
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import yaml

from ros_tui.ui.entries.base import BridgeEntry, Post
from ros_tui.ui.fields import flow_yaml
from ros_tui.ui.nav import Area, Commit, Editing, NavState, Tab, UndoEntry

PARAM = 'par'  # UndoEntry kind of a parameter change.

# (group title, NodeInfo attribute, the kind its entries open as), in the order they are listed.
INTERFACE_GROUPS = (
    ('Publishes', 'publishers', 'topics'),
    ('Subscribes', 'subscribers', 'topics'),
    ('Serves', 'service_servers', 'services'),
    ('Calls', 'service_clients', 'services'),
    ('Action server', 'action_servers', 'actions'),
    ('Action client', 'action_clients', 'actions'),
)

_BOOL = re.compile(r'^(true|false)$', re.IGNORECASE)
_NO_CHANGE = object()  # Undo data: the parameter had no change before.


class Param(NamedTuple):
    name: str
    type: str  # The bridge's type label: bool, int, double, string, byte[], bool[], int[], …
    value: Any


class Interface(NamedTuple):
    kind: str  # The kind it opens as: topics, services or actions.
    name: str


@dataclass
class NodeData:
    """What is known about one node: None until the bridge has answered."""

    groups: list[tuple[str, list[Interface]]] | None = None
    params: list[Param] | None = None
    changes: dict[str, Any] = field(default_factory=dict)  # Parameter name -> its new, not yet set value.
    info_error: str = ''
    params_error: str = ''

    def interfaces(self) -> list[Interface]:
        return [row for _, rows in self.groups or () for row in rows]


def render_value(value: Any) -> str:
    """A parameter value as YAML: what the PARAMETERS area shows and what set_node_parameter sends.

    It parses back (yaml.safe_load) to the same value and type: a string that reads as something
    else stays quoted ('true', '10'), and 1e-05 stays a double.
    """
    return '' if value is None else flow_yaml(value)


def edit_text(param: Param, value: Any) -> str:
    """The text an edit of `param` starts from: a string as typed, anything else as YAML."""
    return value if param.type == 'string' else render_value(value)


def _bool(text: str) -> bool:
    if not _BOOL.match(text):
        raise ValueError(text)
    return text.lower() == 'true'


def _list(text: str) -> list:
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError:
        value = None
    if not isinstance(value, list):
        raise ValueError(text)
    return value


# Parameter type -> (parse the typed text, what it needs, for the error). Array types parse as lists.
_PARSERS = {
    'bool': (_bool, 'true or false'),
    'int': (int, 'a whole number'),
    'double': (float, 'a number'),
    'string': (str, ''),
}


def parse_value(param: Param, text: str) -> Any:
    """The value typed for `param`, checked against its type. Raises ValueError with the message
    the user sees, which names the parameter and quotes what was typed."""
    text = text.strip()
    parse, needs = _PARSERS.get(param.type, (_list, 'a list like [1, 2]'))
    try:
        return parse(text)
    except ValueError:
        raise ValueError(f'{param.name} needs {needs}, got "{text}"') from None


class NodeEntry(BridgeEntry):
    """The node entry kind."""

    def __init__(self, bridge: Any, post: Post | None = None):
        super().__init__(bridge, post)
        self._nodes: dict[str, NodeData] = {}

    def data(self, tab: Tab) -> NodeData:
        return self._nodes.setdefault(tab.name, NodeData())

    def param(self, tab: Tab, row: int) -> Param | None:
        params = self.data(tab).params or []
        return params[row] if 0 <= row < len(params) else None

    def param_named(self, tab: Tab, name: str) -> Param | None:
        return next((param for param in self.data(tab).params or () if param.name == name), None)

    # ---------- loading ----------
    def on_open(self, nav: NavState, tab: Tab) -> None:
        """Ask for the node's interfaces and parameters each time its tab is opened or gone to.
        What is shown stays until the answer replaces it; changes not set yet are kept."""
        name = tab.name
        self._bridge.get_node_info(name, lambda info, error: self._post(lambda: self._info_done(name, info, error)))
        self._bridge.list_node_parameters(
            name, lambda params, error: self._post(lambda: self._params_done(name, params, error)))

    def _info_done(self, name: str, info: Any, error: str | None) -> None:
        data = self._nodes.setdefault(name, NodeData())
        data.info_error = error or ''
        if not error:
            data.groups = [(title, [Interface(kind, entry.name) for entry in getattr(info, attr)])
                           for title, attr, kind in INTERFACE_GROUPS if getattr(info, attr)]

    def _params_done(self, name: str, params: list | None, error: str | None) -> None:
        data = self._nodes.setdefault(name, NodeData())
        data.params_error = error or ''
        if not error:
            data.params = [Param(*param) for param in params or ()]
            names = {param.name for param in data.params}
            data.changes = {key: value for key, value in data.changes.items() if key in names}

    # ---------- rows ----------
    def row_count(self, tab: Tab, area: Area) -> int:
        data = self.data(tab)
        if area.id == 'ifs':
            return len(data.interfaces())
        return len(data.params or ()) if area.id == PARAM else 0

    def activate_row(self, nav: NavState, tab: Tab, area: Area, row: int, how: str) -> bool:
        """enter on an interface opens it in a tab."""
        rows = self.data(tab).interfaces() if area.id == 'ifs' else []
        if not 0 <= row < len(rows):
            return False
        nav.open_entity(rows[row].kind, rows[row].name, how)
        return True

    # ---------- editing ----------
    def start_edit(self, tab: Tab, area: Area, row: int, clear: bool) -> Editing | None:
        param = self.param(tab, row) if area.id == PARAM else None
        if param is None or param.type == '?':
            return None
        value = self.data(tab).changes.get(param.name, param.value)
        text = '' if clear else edit_text(param, value)
        return Editing(PARAM, row, text, old=text, fresh=param.type == 'bool', field=param.name)

    def commit_edit(self, tab: Tab, editing: Editing) -> Commit:
        param = self.param_named(tab, editing.field)  # By name: the list may have reloaded meanwhile.
        if param is None:
            return Commit(False, f'{editing.field} is no longer on {tab.name}')
        try:
            value = parse_value(param, editing.value)
        except ValueError as error:
            return Commit(False, str(error))
        changes = self.data(tab).changes
        before = changes.get(param.name, _NO_CHANGE)
        if value == param.value and type(value) is type(param.value):
            changes.pop(param.name, None)
            text = f'{param.name} unchanged'
        else:
            changes[param.name] = value
            text = f'{param.name} = {render_value(value)} (not set yet: space sets it, u undoes)'
        after = changes.get(param.name, _NO_CHANGE)
        undo = UndoEntry(tab.key, PARAM, (param.name, before)) if after != before else None
        return Commit(True, text, undo)

    def undo(self, nav: NavState, entry: UndoEntry) -> str:
        name, before = entry.data
        tab = Tab(*entry.owner.split(':', 1))
        changes = self.data(tab).changes
        if before is _NO_CHANGE:
            changes.pop(name, None)
        else:
            changes[name] = before
        return f'undid the change to {name} on {tab.name}'

    # ---------- verbs ----------
    def verb(self, nav: NavState, tab: Tab | None, name: str, how: str, arg: Any = None) -> bool:
        if name == 'primary':
            self.set_changed(nav, tab, how)
            return True
        return super().verb(nav, tab, name, how, arg)

    def set_changed(self, nav: NavState, tab: Tab, how: str) -> None:
        """space / ^s: set every changed parameter on the node, one set_node_parameter call each.
        A change clears when its set succeeds; a failed one stays changed."""
        changes = self.data(tab).changes
        if not changes:
            nav.show_toast('change a value first (enter edits it)', 'bad')
            nav.log_line(how, 'no changed parameters to set')
            return
        count = len(changes)
        for name, value in list(changes.items()):
            self._bridge.set_node_parameter(
                tab.name, name, render_value(value),
                lambda error, name=name, value=value: self._post(lambda: self._set_done(nav, tab, name, value, error)))
        nav.log_line(how, f'set {count} parameter{"s" if count > 1 else ""} on {tab.name}')

    def _set_done(self, nav: NavState, tab: Tab, name: str, value: Any, error: str | None) -> None:
        if error:
            nav.add_activity(tab, f'✗ set {name}: {error}', 'r')
            return
        data = self.data(tab)
        data.params = [param._replace(value=value) if param.name == name else param for param in data.params or ()]
        if data.changes.get(name, _NO_CHANGE) == value:
            data.changes.pop(name)
            # The change is on the node now: undoing it here would only log a no-op "undid".
            nav.undo_stack[:] = [entry for entry in nav.undo_stack
                                 if not (entry.owner == tab.key and entry.kind == PARAM and entry.data[0] == name)]
        nav.add_activity(tab, f'✓ set {name} = {render_value(value)}', 'g')
