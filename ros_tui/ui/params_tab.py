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

"""Parameters tab: list nodes on the left, view/edit parameters on the right."""

import yaml
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, RichLog, Static

from ros_tui.ui.filterable_list import FilterableList
from ros_tui.ui.messages import NodeParametersReady, ParameterSetCompleted


class ParamsTab(Horizontal):
    def __init__(self, bridge, **kwargs):
        super().__init__(**kwargs)
        self._bridge = bridge
        self._current_node: str | None = None
        self._params: list = []  # [(name, type_label, value), ...]

    def compose(self):
        yield FilterableList(placeholder='filter nodes…', classes='entity-list')
        with Vertical(classes='right-pane'):
            yield Static('Select a node to view its parameters', id='params-node-label')
            yield DataTable(id='params-table', cursor_type='row')
            with Horizontal(classes='controls'):
                yield Button('Refresh', id='refresh-button', disabled=True)
                yield Button('Set', id='set-button', variant='primary', disabled=True)
            yield Input(placeholder='new value (YAML)', id='value-input')
            yield Static('', id='params-error')
            yield RichLog(id='params-log', markup=True)

    def on_mount(self) -> None:
        table = self.query_one('#params-table', DataTable)
        table.add_columns('Parameter', 'Type', 'Value')

    def set_entries(self, nodes) -> None:
        self.query_one(FilterableList).set_entries(nodes)

    def focus_filter(self) -> None:
        self.query_one(FilterableList).focus_filter()

    def primary_action(self) -> None:
        self._set_parameter()

    def secondary_action(self) -> None:
        self._load_params()

    def clear_log(self) -> None:
        self.query_one('#params-log', RichLog).clear()

    # ---------------------------------------------------------------- selection

    def on_filterable_list_selected(self, message: FilterableList.Selected) -> None:
        message.stop()
        self._current_node = message.entry.name
        self.query_one('#params-node-label', Static).update(
            f'[bold]{self._current_node}[/bold]  loading…'
        )
        self.query_one('#refresh-button', Button).disabled = True
        self.query_one('#set-button', Button).disabled = True
        self._clear_error()
        self._load_params()

    def _load_params(self) -> None:
        node_name = self._current_node
        if node_name is None:
            return
        self.query_one('#params-node-label', Static).update(
            f'[bold]{node_name}[/bold]  loading…'
        )
        self.query_one('#refresh-button', Button).disabled = True
        self.query_one('#set-button', Button).disabled = True

        def on_done(params, error):
            self.post_message(NodeParametersReady(node_name, params, error))

        self._bridge.list_node_parameters(node_name, on_done)

    # ---------------------------------------------------------------- messages

    def on_node_parameters_ready(self, message: NodeParametersReady) -> None:
        if message.node_name != self._current_node:
            return
        self.query_one('#refresh-button', Button).disabled = False
        if message.error:
            self.query_one('#params-node-label', Static).update(
                f'[bold]{self._current_node}[/bold]'
            )
            self._show_error(message.error)
            return
        self._params = message.params or []
        self._populate_table(self._params)
        self.query_one('#params-node-label', Static).update(
            f'[bold]{self._current_node}[/bold]  ({len(self._params)} parameters)'
        )
        self._clear_error()

    def on_parameter_set_completed(self, message: ParameterSetCompleted) -> None:
        if message.node_name != self._current_node:
            return
        log = self.query_one('#params-log', RichLog)
        if message.error:
            log.write(f'[red]set {message.param_name}: {message.error}[/red]')
            self._show_error(message.error)
        else:
            log.write(f'[green]set {message.param_name} OK[/green]')
            self._clear_error()
            self._load_params()

    # ---------------------------------------------------------------- table

    def _populate_table(self, params: list) -> None:
        table = self.query_one('#params-table', DataTable)
        table.clear()
        for name, type_label, value in params:
            table.add_row(name, type_label, _format_value(value), key=name)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        row_key = event.row_key.value
        for name, _type_label, value in self._params:
            if name == row_key:
                self.query_one('#value-input', Input).value = _yaml_value(value)
                self.query_one('#set-button', Button).disabled = (self._current_node is None)
                break

    # ---------------------------------------------------------------- set

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'refresh-button':
            self._load_params()
        elif event.button.id == 'set-button':
            self._set_parameter()

    def _set_parameter(self) -> None:
        if self._current_node is None:
            return
        table = self.query_one('#params-table', DataTable)
        if table.cursor_row < 0 or not self._params:
            return
        try:
            row_key = table.get_row_at(table.cursor_row)[0]  # first cell = param name
        except Exception:
            return
        value_str = self.query_one('#value-input', Input).value.strip()
        if not value_str:
            self._show_error('value is empty')
            return
        node_name = self._current_node
        param_name = str(row_key)
        self._clear_error()

        def on_done(error):
            self.post_message(ParameterSetCompleted(node_name, param_name, error))

        self._bridge.set_node_parameter(node_name, param_name, value_str, on_done)

    # ---------------------------------------------------------------- helpers

    def _show_error(self, text: str) -> None:
        err = self.query_one('#params-error', Static)
        err.update(f'[red]{text}[/red]')
        err.display = True

    def _clear_error(self) -> None:
        err = self.query_one('#params-error', Static)
        err.update('')
        err.display = False


def _format_value(value) -> str:
    if value is None:
        return ''
    if isinstance(value, list):
        return repr(value)
    return str(value)


def _yaml_value(value) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return yaml.dump(value, default_flow_style=True).strip()
    return str(value)
