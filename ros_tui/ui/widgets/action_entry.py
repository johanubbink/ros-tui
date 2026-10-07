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

"""The action entry's button row and panels (the actions branch of the design's renderEntry).

"▶ Send goal space" (disabled, with the reason, while a goal runs on another action) and "■ Cancel
goal s" (the stop look while this entry's goal runs, else disabled), then GOAL (field rows) and
RESULT side by side: the goal's state pill and time, and its newest feedback or its result.
Everything shown comes from the ActionEntry provider (entries/action.py).
"""

from rich.text import Text

from ros_tui.ui.entries.action import CANCELED, EXECUTING, SENDING, SUCCEEDED, ActionData, ActionEntry
from ros_tui.ui.entries.message import EDITOR
from ros_tui.ui.nav import Area, NavState, Tab
from ros_tui.ui.widgets.base import button, keyed, primary_look, spread, style
from ros_tui.ui.widgets.field_rows import editor_panel, shown_value
from ros_tui.ui.widgets.panel import Panel, pill, waiting

PILLS = {  # A goal's state -> its pill's (text, colour, background); any other state is bad.
    SENDING: ('sending…', 'live', 'live-bg'),
    EXECUTING: (EXECUTING, 'live', 'live-bg'),
    SUCCEEDED: (SUCCEEDED, 'ok', 'ok-bg'),
    CANCELED: (CANCELED, 'warn', 'warn-bg'),
}


def _entry(nav: NavState, tab: Tab) -> tuple[ActionEntry, ActionData]:
    entry = nav.provider.for_tab(tab)
    return entry, entry.data(tab)


def action_toolbar(nav: NavState, tab: Tab, width: int) -> Text:
    """Send goal and Cancel goal, as the single-running-goal rule allows them."""
    entry, _ = _entry(nav, tab)
    running = entry.executing()
    here = running == tab
    left = button('▶ Send goal', 'space', primary_look(nav, tab, 'off' if running else 'pri'))
    if running and not here:
        left.append(f' a goal is running on {running.name}', style('dim'))
    left.append(' ')
    left.append_text(button('■ Cancel goal', 's', 'stop' if here else 'off'))
    return spread(left, keyed('[ ]', 'earlier goals', 'dim'), width, optional=True)


def result_panel(nav: NavState, tab: Tab, entry: ActionEntry, data: ActionData, area: Area) -> Panel:
    """RESULT: the last goal's state and time, then its newest feedback or its result."""
    panel = Panel(area.title, wrap=True)
    goal = data.goal
    if goal is None:
        panel.hint = Text('no goal yet')
        return panel
    if data.editor is None:
        panel.lines = waiting(data.error)
        return panel
    shows, rows = entry.result_rows(tab)
    label, color, bg = PILLS.get(goal.state, (goal.state, 'bad', 'bad-bg'))
    panel.hint = pill(label, color, bg) + Text(f' {goal.elapsed(nav.clock()):.1f} s')
    if goal.running:
        panel.hint.append(' · canceling…' if goal.canceling else ' · live feedback')
    elif shows == 'feedback':
        panel.hint.append(' · last feedback')
    panel.errline = goal.error
    panel.lines = [Text.assemble((row.field, style('syn-key')), ': ',
                                 Text('–', style('dim')) if row.value is None else shown_value(row)) for row in rows]
    if not rows and not goal.error:
        panel.lines = [Text('waiting for feedback…' if goal.running else 'empty result (no fields)', style('dim'))]
    panel.cursor = nav.row_index(area) if rows else None
    return panel


def action_panels(nav: NavState, tab: Tab) -> list[Panel]:
    """GOAL and RESULT, in the order of the entry's areas."""
    entry, data = _entry(nav, tab)
    return [editor_panel(nav, tab, data, area) if area.id == EDITOR else result_panel(nav, tab, entry, data, area)
            for area in nav.areas()]
