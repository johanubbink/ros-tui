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

"""Nodes tab: pick a node on the left; see its interfaces and parameters on the right.

The right pane stacks an Interfaces tree (à la ``ros2 node info``) over the parameter table
and its set controls. Selecting an interface leaf jumps to the matching Topics/Services/
Actions tab with that entity pre-selected.
"""

import yaml
from textual import on
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static, Tree

from ros_tui.ui.entity_tab import EntityTab
from ros_tui.ui.filterable_list import FilterableList
from ros_tui.ui.messages import (
    NavigateToEntity,
    NodeInfoReady,
    NodeParametersReady,
    ParameterSetCompleted,
)

# (label, NodeInfo attribute, destination tab id, expanded-by-default).
# Client branches start collapsed: they are often empty and rarely the thing you came for.
_BRANCHES = (
    ('Publishers', 'publishers', 'topics', True),
    ('Subscribers', 'subscribers', 'topics', True),
    ('Service Servers', 'service_servers', 'services', True),
    ('Service Clients', 'service_clients', 'services', False),
    ('Action Servers', 'action_servers', 'actions', True),
    ('Action Clients', 'action_clients', 'actions', False),
)

_PLACEHOLDER = 'Select a node to view its interfaces and parameters'


class NodesTab(EntityTab):
    """Nodes tab: a node's interfaces tree + parameter table, sharing the EntityTab contract."""

    def __init__(self, bridge, **kwargs):
        super().__init__(bridge, **kwargs)
        self._current_node: str | None = None
        self._info = None  # ros_tui.ros.graph.NodeInfo once loaded.
        self._params: list | None = None  # [(name, type_label, value), ...] once loaded.
        self._seeded_value = ''  # The value the tab last auto-seeded into the edit box.

    def compose(self):
        yield FilterableList(placeholder='filter nodes…', classes='entity-list')
        with Vertical(classes='right-pane'):
            yield Static(_PLACEHOLDER, id='node-header')
            yield Tree('Interfaces', id='node-interfaces')
            with Vertical(id='node-params-group'):
                yield DataTable(id='node-params', cursor_type='row')
                with Horizontal(classes='controls'):
                    yield Input(placeholder='new value (YAML)', id='node-param-value')
                    yield Button('Refresh', id='node-param-refresh', disabled=True)
                    yield Button('Set', id='node-param-set', variant='primary', disabled=True)
                yield Static('', id='node-param-status')

    def on_mount(self) -> None:
        self.query_one('#node-params', DataTable).add_columns('Parameter', 'Type', 'Value')
        tree = self.query_one('#node-interfaces', Tree)
        tree.show_root = False
        tree.border_title = 'Interfaces'
        self.query_one('#node-params-group').border_title = 'Parameters'

    def primary_action(self) -> None:
        """ctrl+s — set the selected parameter to the value in the input box."""
        self._set_parameter()

    def secondary_action(self) -> None:
        """ctrl+k — reload the node's interfaces and parameters."""
        self._reload()

    def clear_log(self) -> None:
        """ctrl+l — clear the parameter status line (this tab has no scrolling log)."""
        self._clear_error()

    # ---------------------------------------------------------------- selection

    @on(FilterableList.Selected)
    def _on_node_selected(self, message: FilterableList.Selected) -> None:
        message.stop()
        self._current_node = message.entry.name
        self._info = None
        self._params = None
        self.query_one('#node-interfaces', Tree).clear()
        self.query_one('#node-params', DataTable).clear()
        self.query_one('#node-param-value', Input).value = ''  # Fresh node, fresh edit box.
        self._seeded_value = ''
        self.query_one('#node-param-refresh', Button).disabled = True
        self.query_one('#node-param-set', Button).disabled = True
        self._clear_error()
        self._refresh_header()
        self._reload()

    def _reload(self) -> None:
        self._clear_error()
        self._load_node_info()
        self._load_params()

    def _load_node_info(self) -> None:
        node_name = self._current_node
        if node_name is None:
            return

        def on_done(info, error):
            self.post_message(NodeInfoReady(node_name, info, error))

        self._bridge.get_node_info(node_name, on_done)

    def _load_params(self) -> None:
        node_name = self._current_node
        if node_name is None:
            return
        self.query_one('#node-param-refresh', Button).disabled = True

        def on_done(params, error):
            self.post_message(NodeParametersReady(node_name, params, error))

        self._bridge.list_node_parameters(node_name, on_done)

    # ---------------------------------------------------------------- messages

    def on_node_info_ready(self, message: NodeInfoReady) -> None:
        message.stop()
        if message.node_name != self._current_node:
            return  # Stale result from a superseded selection.
        if message.error:
            self._show_error(message.error)
            return
        self._info = message.info
        self._populate_tree(message.info)
        self._refresh_header()

    def on_node_parameters_ready(self, message: NodeParametersReady) -> None:
        message.stop()
        if message.node_name != self._current_node:
            return
        self.query_one('#node-param-refresh', Button).disabled = False
        if message.error:
            self._show_error(message.error)
            return
        self._params = message.params or []
        self._populate_table(self._params)
        self._refresh_header()

    def on_parameter_set_completed(self, message: ParameterSetCompleted) -> None:
        message.stop()
        if message.node_name != self._current_node:
            return
        if message.error:
            self._show_error(message.error)
        else:
            self._show_success(f'set {message.param_name}')
            self._load_params()

    # ---------------------------------------------------------------- interfaces tree

    def _populate_tree(self, info) -> None:
        tree = self.query_one('#node-interfaces', Tree)
        tree.clear()
        for label, attr, tab_id, expand in _BRANCHES:
            items = getattr(info, attr)
            branch = tree.root.add(f'{label} ({len(items)})', expand=expand)
            for entry in items:
                type_name = entry.types[0] if entry.types else ''
                branch.add_leaf(f'{entry.name}    {type_name}', data=(tab_id, entry))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        data = event.node.data
        if data is None:
            return  # A category branch — Tree handles expand/collapse itself.
        tab_id, entry = data
        self.post_message(NavigateToEntity(tab_id, entry))

    # ---------------------------------------------------------------- parameters table

    def _populate_table(self, params: list) -> None:
        table = self.query_one('#node-params', DataTable)
        table.clear()
        for name, type_label, value in params:
            table.add_row(name, type_label, _render_value(value), key=name)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        if event.row_key is None:
            return
        row_key = event.row_key.value
        for name, _type_label, value in self._params or []:
            if name == row_key:
                input_box = self.query_one('#node-param-value', Input)
                rendered = _render_value(value)
                # Reseed only when the box is pristine; every cursor move fires this handler,
                # so blindly overwriting would discard a value the user typed but hasn't Set.
                if input_box.value in ('', self._seeded_value):
                    input_box.value = rendered
                    self._seeded_value = rendered
                self.query_one('#node-param-set', Button).disabled = self._current_node is None
                break

    # ---------------------------------------------------------------- set

    @on(Button.Pressed, '#node-param-refresh')
    def _on_refresh_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._reload()

    @on(Button.Pressed, '#node-param-set')
    def _on_set_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self._set_parameter()

    def _set_parameter(self) -> None:
        if self._current_node is None:
            return
        table = self.query_one('#node-params', DataTable)
        if table.cursor_row < 0 or not self._params:
            return
        try:
            row_key = table.get_row_at(table.cursor_row)[0]  # first cell = param name
        except Exception:
            return
        value_str = self.query_one('#node-param-value', Input).value.strip()
        if not value_str:
            self._show_error('enter a value to set')
            return
        node_name = self._current_node
        param_name = str(row_key)
        self._clear_error()

        def on_done(error):
            self.post_message(ParameterSetCompleted(node_name, param_name, error))

        self._bridge.set_node_parameter(node_name, param_name, value_str, on_done)

    # ---------------------------------------------------------------- helpers

    def _refresh_header(self) -> None:
        header = self.query_one('#node-header', Static)
        if self._current_node is None:
            header.update(_PLACEHOLDER)
            return
        parts = [f'[bold]{self._current_node}[/bold]']
        if self._info is not None:
            i = self._info
            parts.append(
                f'{len(i.publishers)} pub · {len(i.subscribers)} sub · '
                f'{len(i.service_servers)} srv · {len(i.service_clients)} cli · '
                f'{len(i.action_servers)} act · {len(i.action_clients)} acli'
            )
        if self._params is not None:
            parts.append(f'{len(self._params)} params')
        if self._info is None and self._params is None:
            parts.append('loading…')
        header.update('   '.join(parts))

    def _show_error(self, text: str) -> None:
        self.query_one('#node-param-status', Static).update(f'[red]✗ {text}[/red]')

    def _show_success(self, text: str) -> None:
        self.query_one('#node-param-status', Static).update(f'[green]✓ {text}[/green]')

    def _clear_error(self) -> None:
        self.query_one('#node-param-status', Static).update('')


def _render_value(value) -> str:
    """Render a parameter value as the YAML it round-trips through the edit box on Set.

    Used for both the table's value column and the input seed, so what is shown parses
    back (via ``yaml.safe_load`` on Set) to the same value *and type*: strings stay
    strings (quoted when their text would otherwise parse as a bool/int/float), and
    exponential doubles like ``1e-05`` stay doubles rather than ``str``.
    """
    if value is None:
        return ''
    text = yaml.safe_dump(value, default_flow_style=True).strip()
    # safe_dump appends a '...' document-end marker after a bare scalar root; drop it.
    if text.endswith('\n...'):
        text = text[: -len('\n...')].rstrip()
    return text
