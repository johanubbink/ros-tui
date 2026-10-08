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

Pure Python (no textual, no rclpy). A kept edit is a *change*: shown as
"new was old" and sent only by space / ^s (`set_node_parameter`, one call per changed
parameter). u undoes a change, in this tab only.

The node's interfaces and parameters are asked for when its tab is opened. The bridge answers on
its own thread; `post` brings each answer to the UI thread (the app posts a message) before it
touches the model. Until an answer is in, the area says "loading…".
"""

from typing import Any, NamedTuple

from ros_tui.ui.entries.base import Area, Commit, Context, Editing, Entry, Tab, UndoEntry, Verb
from ros_tui.ui.fields import BOOL_TYPE, flow_yaml, parse_list, parse_scalar
from ros_tui.ui.nav import NavState

PARAM = 'par'  # The area id of PARAMETERS; its undo steps are tagged with the parameter's name.

# (group title, NodeInfo attribute, the kind its entries open as), in the order they are listed.
INTERFACE_GROUPS = (
    ('Publishes', 'publishers', 'topics'),
    ('Subscribes', 'subscribers', 'topics'),
    ('Serves', 'service_servers', 'services'),
    ('Calls', 'service_clients', 'services'),
    ('Action server', 'action_servers', 'actions'),
    ('Action client', 'action_clients', 'actions'),
)

_NO_CHANGE = object()  # Undo data: the parameter had no change before.


class Param(NamedTuple):
    name: str
    type: str  # The bridge's type label: bool, int, double, string, byte[], bool[], int[], …
    value: Any


class Interface(NamedTuple):
    kind: str  # The kind it opens as: topics, services or actions.
    name: str


def render_value(value: Any) -> str:
    """A parameter value as YAML: what the PARAMETERS area shows and what set_node_parameter sends.

    It parses back (yaml.safe_load) to the same value and type: a string that reads as something
    else stays quoted ('true', '10'), and 1e-05 stays a double.
    """
    return '' if value is None else flow_yaml(value)


def edit_text(param: Param, value: Any) -> str:
    """The text an edit of `param` starts from: a string as typed, anything else as YAML."""
    return value if param.type == 'string' else render_value(value)


# The parameter types read as a message field of the same type (fields.parse_scalar).
_SCALAR_LABELS = {'bool': BOOL_TYPE, 'int': 'int64', 'double': 'double'}


def parse_value(param: Param, text: str) -> Any:
    """The value typed for `param`, checked against its type. Raises ValueError with the message
    the user sees, which names the parameter and quotes what was typed. Numbers and bools are read
    as message fields are; a string is the text as typed; an array type takes a YAML list, as an
    array field does."""
    text = text.strip()
    if param.type in _SCALAR_LABELS:
        return parse_scalar(_SCALAR_LABELS[param.type], param.name, text)
    if param.type == 'string':
        return text
    return parse_list(param.name, text)


class NodeEntry(Entry):
    """A node: what is known about it is None until the bridge has answered."""

    AREAS = (Area('ifs', 'INTERFACES', 'open it'), Area(PARAM, 'PARAMETERS', 'edit', True))

    def __init__(self, tab: Tab, ctx: Context | None = None):
        super().__init__(tab, ctx)
        self.groups: list[tuple[str, list[Interface]]] | None = None
        self.params: list[Param] | None = None
        self.changes: dict[str, Any] = {}  # Parameter name -> its new, not yet set value.
        self.info_error = ''
        self.params_error = ''

    def interfaces(self) -> list[Interface]:
        return [row for _, rows in self.groups or () for row in rows]

    def param(self, row: int) -> Param | None:
        params = self.params or []
        return params[row] if 0 <= row < len(params) else None

    def param_named(self, name: str) -> Param | None:
        return next((param for param in self.params or () if param.name == name), None)

    # ---------- loading ----------
    def on_open(self, nav: NavState) -> None:
        """Ask for the node's interfaces and parameters each time its tab is opened or gone to.
        What is shown stays until the answer replaces it; changes not set yet are kept."""
        name = self.tab.name
        self._bridge.get_node_info(name, lambda info, error: self._post(lambda: self._info_done(info, error)))
        self._bridge.list_node_parameters(name, lambda params, error: self._post(lambda: self._params_done(params, error)))

    def _info_done(self, info: Any, error: str | None) -> None:
        self.info_error = error or ''
        if not error:
            self.groups = [(title, [Interface(kind, entry.name) for entry in getattr(info, attr)])
                           for title, attr, kind in INTERFACE_GROUPS if getattr(info, attr)]

    def _params_done(self, params: list | None, error: str | None) -> None:
        self.params_error = error or ''
        if not error:
            self.params = [Param(*param) for param in params or ()]
            names = {param.name for param in self.params}
            self.changes = {key: value for key, value in self.changes.items() if key in names}

    # ---------- rows ----------
    def row_count(self, area: Area) -> int:
        if area.id == 'ifs':
            return len(self.interfaces())
        return len(self.params or ()) if area.id == PARAM else 0

    def activate_row(self, nav: NavState, area: Area, row: int, how: str) -> bool:
        """enter on an interface opens it in a tab."""
        rows = self.interfaces() if area.id == 'ifs' else []
        if not 0 <= row < len(rows):
            return False
        nav.open_entity(rows[row].kind, rows[row].name, how)
        return True

    # ---------- editing ----------
    def start_edit(self, area: Area, row: int, clear: bool) -> Editing | None:
        param = self.param(row) if area.id == PARAM else None
        if param is None or param.type == '?':
            return None
        value = self.changes.get(param.name, param.value)
        text = '' if clear else edit_text(param, value)
        return Editing(PARAM, row, text, old=text, fresh=param.type == 'bool', field=param.name)

    def commit_edit(self, editing: Editing) -> Commit:
        param = self.param_named(editing.field)  # By name: the list may have reloaded meanwhile.
        if param is None:
            return Commit(False, f'{editing.field} is no longer on {self.tab.name}')
        try:
            value = parse_value(param, editing.value)
        except ValueError as error:
            return Commit(False, str(error))
        changes = self.changes
        before = changes.get(param.name, _NO_CHANGE)
        if value == param.value and type(value) is type(param.value):
            changes.pop(param.name, None)
            text = f'{param.name} unchanged'
        else:
            changes[param.name] = value
            text = f'{param.name} = {render_value(value)} (not set yet: space sets it, u undoes)'
        after = changes.get(param.name, _NO_CHANGE)
        undo = UndoEntry(self.tab, lambda nav: self._undo(param.name, before), param.name) if after != before else None
        return Commit(True, text, undo)

    def _undo(self, name: str, before: Any) -> str:
        if before is _NO_CHANGE:
            self.changes.pop(name, None)
        else:
            self.changes[name] = before
        return f'undid the change to {name} on {self.tab.name}'

    # ---------- verbs ----------
    def verbs(self) -> dict[str, Verb]:
        return {'primary': lambda nav, how, _: self._set_changed(nav, how), 'yank': self._yank, 'paste': self._paste}

    @staticmethod
    def _yank(nav: NavState, how: str, _: Any) -> None:
        nav.feedback.refuse(how, 'nothing to copy on a node', 'nothing to copy here')

    @staticmethod
    def _paste(nav: NavState, how: str, _: Any) -> None:
        nav.feedback.refuse(how, 'nothing copied yet (y copies)' if nav.register is None
                            else 'nothing to paste into on a node', 'no editor here')

    def _set_changed(self, nav: NavState, how: str) -> None:
        """space / ^s: set every changed parameter on the node, one set_node_parameter call each.
        A change clears when its set succeeds; a failed one stays changed."""
        changes = self.changes
        if not changes:
            nav.feedback.refuse(how, 'change a value first (enter edits it)', 'no changed parameters to set')
            return
        count = len(changes)
        for name, value in list(changes.items()):
            self._bridge.set_node_parameter(
                self.tab.name, name, render_value(value),
                lambda error, name=name, value=value: self._post(lambda: self._set_done(nav, name, value, error)))
        nav.feedback.log_line(how, f'set {count} parameter{"s" if count > 1 else ""} on {self.tab.name}')

    def _set_done(self, nav: NavState, name: str, value: Any, error: str | None) -> None:
        tab = self.tab
        if error:
            nav.feedback.add_activity(tab, f'✗ set {name}: {error}', 'r')
            return
        self.params = [param._replace(value=value) if param.name == name else param for param in self.params or ()]
        if self.changes.get(name, _NO_CHANGE) == value:
            self.changes.pop(name)
            # The change is on the node now: undoing it here would only log a no-op "undid".
            nav.drop_undo(lambda entry: entry.owner == tab and entry.tag == name)
        nav.feedback.add_activity(tab, f'✓ set {name} = {render_value(value)}', 'g')
