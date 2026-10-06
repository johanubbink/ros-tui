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

"""The topic entry's button rows and panels (the topics branch of the design's renderEntry).

Echo: "▶ Start echo space" / "■ Stop echo space" with what the echo counted, then LATEST MESSAGE,
one row per field: "[x] data   'chatter 3'", live ("● live") or frozen ("❄ FROZEN +N new since").
Publish: "▶ Publish once space" and "↻ Repeat at 10 Hz r" / "■ Stop repeating at 10 Hz s" with the
rate (typed in place after R), then the MESSAGE editor. Everything shown comes from the TopicEntry
provider (entries/topic.py).
"""

from rich.style import Style
from rich.text import Text

from ros_tui.ui.entries.topic import ECHO, RATE, TopicData, TopicEntry, rate_text
from ros_tui.ui.nav import EDIT, Area, NavState, Tab
from ros_tui.ui.widgets.base import button, edit_value, keyed, spread, style
from ros_tui.ui.widgets.field_rows import editor_panel, shown_value
from ros_tui.ui.widgets.panel import Panel, hint, pill, waiting

KEY_WIDTH = 18  # The field column of LATEST MESSAGE, at least (the design's padEnd(18)).


def _entry(nav: NavState, tab: Tab) -> tuple[TopicEntry, TopicData]:
    entry = nav.provider.for_tab(tab)
    return entry, entry.data(tab)


def topic_counts(nav: NavState, tab: Tab) -> Text:
    """The header's "1 pub · 0 sub", once the bridge has counted them."""
    counts = _entry(nav, tab)[1].counts
    return Text(f'{counts[0]} pub · {counts[1]} sub' if counts else '', style('dim'))


def topic_toolbar(nav: NavState, tab: Tab, width: int) -> Text:
    entry, data = _entry(nav, tab)
    if entry.mode(tab) == 'echo':
        return echo_toolbar(data, width)
    return publish_toolbar(nav, tab, entry, data, width)


def echo_toolbar(data: TopicData, width: int) -> Text:
    """The echo's start / stop button, what it counted, and the keys of the latest message."""
    echo = data.echo
    left = button('■ Stop echo' if echo else '▶ Start echo', 'space', 'stop' if echo else 'pri')
    if echo:
        left.append(f'  {echo.received} received · {echo.hz:.1f} Hz', style('dim'))
        if echo.dropped:
            left.append(f' · {echo.dropped} dropped', style('warn'))
    return spread(left, hint(('enter', 'freezes the values'), ('y', 'copies'), ('e', 'publish'), color='dim'), width)


def publish_toolbar(nav: NavState, tab: Tab, entry: TopicEntry, data: TopicData, width: int) -> Text:
    """Publish once, repeat at the rate (typed in place after R), and how many the repeat sent."""
    repeat = data.repeat
    editing = nav.editing if nav.layer == EDIT and nav.editing and nav.editing.area == RATE else None
    rate = edit_value(editing.value, editing.fresh) if editing else Text(
        rate_text(repeat.rate if repeat else entry.rate(tab)), Style(underline=True))
    label = Text.assemble('■ Stop repeating at ' if repeat else '↻ Repeat at ', rate, ' Hz')
    left = Text.assemble(button('▶ Publish once', 'space', 'pri'), ' ',
                         button(label, 's' if repeat else 'r', 'stop' if repeat else ''), '  ')
    if editing:
        left.append('type a rate · enter keeps · 0.1–100 Hz', style('dim'))
    else:
        left.append_text(hint(entry.rate_note(tab), ('R', 'changes it'), color='dim'))
    if repeat:
        left.append(f'  {repeat.sent(nav.clock())} sent', style('ok'))
    return spread(left, keyed('[ ]', 'earlier messages', 'dim'), width)


def latest_panel(nav: NavState, tab: Tab, entry: TopicEntry, data: TopicData, area: Area) -> Panel:
    """LATEST MESSAGE: live, frozen while the cursor is inside it, or not echoing."""
    panel = Panel(area.title)
    if data.echo is None:
        panel.hint = hint('not echoing', ('space', 'starts'))
    elif entry.frozen(nav, tab):
        panel.hint = Text.assemble(pill('❄ FROZEN', 'warn', 'warn-bg'), ' ',
                                   (f'+{data.new_since} new since', style('warn')), '  ',
                                   hint(('esc', 'goes live'), ('enter', 'shows / hides a field')))
    else:
        panel.hint = Text.assemble(('● live', style('ok')), ' · ', hint(('enter', 'freezes it')))
    if data.editor is None:
        panel.lines = waiting(data.error)
        return panel
    rows = entry.echo_rows(nav, tab)
    width = max(KEY_WIDTH, *(len(row.field) + 1 for row in rows)) if rows else KEY_WIDTH
    nobody = entry.publishers(nav, tab) == 0
    for row in rows:
        shown = row.field not in data.hidden
        line = Text.assemble('[x] ' if shown else '[ ] ', (row.field.ljust(width), style('syn-key')))
        if not shown:
            line.append('hidden', style('dim'))
        elif data.echo is None:
            line.append('–', style('dim'))
        elif row.value is None:
            line.append('waiting — nobody publishes this yet' if nobody else 'waiting for the first message…',
                        style('dim'))
        else:
            line.append_text(shown_value(row))
        panel.lines.append(line)
    panel.cursor = nav.row_index(area) if rows else None
    return panel


def topic_panels(nav: NavState, tab: Tab) -> list[Panel]:
    """LATEST MESSAGE (Echo) or MESSAGE (Publish), as the entry's one area."""
    entry, data = _entry(nav, tab)
    return [latest_panel(nav, tab, entry, data, area) if area.id == ECHO else editor_panel(nav, tab, data, area)
            for area in nav.areas()]
