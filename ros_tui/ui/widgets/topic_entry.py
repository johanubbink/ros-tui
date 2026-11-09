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

"""The topic entry's button rows and panels.

Echo: "▶ Start echo space" / "■ Stop echo space", then LATEST MESSAGE, one row per field:
"[x] data   'chatter 3'", live ("● live") or frozen ("❄ FROZEN +N new since"), with what the echo
counted at the right of its title.
Publish: "▶ Publish once space" and "↻ Repeat at 10 Hz r" / "■ Stop repeating at 10 Hz s" with the
rate (typed in place after R), then the MESSAGE editor. Everything shown comes from the
TopicEntry (entries/topic.py).
"""

from rich.style import Style
from rich.text import Text

from ros_tui.ui.entries.base import OUT, RATE, Area
from ros_tui.ui.entries.topic import RATE_RANGE, TopicEntry, rate_text
from ros_tui.ui.fields import Row
from ros_tui.ui.keymap import key_for
from ros_tui.ui.nav import NavState
from ros_tui.ui.widgets.base import (HISTORY_KEYS, button, clickable, column_width, edit_value, keyed, primary_look, spread,
                                     style)
from ros_tui.ui.widgets.field_rows import editor_panel, shown_value
from ros_tui.ui.widgets.panel import Panel, hint, pill, waiting

KEY_WIDTH = 18  # The field column of LATEST MESSAGE, at least.


def topic_counts(nav: NavState, entry: TopicEntry) -> Text:
    """The header's "1 pub · 0 sub", as the graph counts them."""
    counts = entry.counts(nav)
    return Text(f'{counts[0]} pub · {counts[1]} sub' if counts else '', style('dim'))


def topic_toolbar(nav: NavState, entry: TopicEntry, width: int) -> Text:
    return (echo_toolbar if entry.mode == 'echo' else publish_toolbar)(nav, entry, width)


def echo_toolbar(nav: NavState, entry: TopicEntry, width: int) -> Text:
    """The echo's start / stop button and the keys of the latest message."""
    look = primary_look(nav, entry.tab, 'stop' if entry.echo else 'pri')
    left = button('■ Stop echo' if entry.echo else '▶ Start echo', 'primary', look)
    keys = hint((key_for('go_down'), 'freezes the values'), (key_for('verb', 'yank'), 'copies'),
                (key_for('switch_mode'), 'publish'), color='dim')
    return spread(left, keys, width, optional=True)


def echo_counts(entry: TopicEntry) -> Text:
    """What the echo counted, for the right of LATEST MESSAGE's title: "3 received · 1.0 Hz"."""
    echo = entry.echo
    if echo is None:
        return Text()
    text = Text(f'{echo.received} received · {echo.hz:.1f} Hz')
    if echo.dropped:
        text.append(f' · {echo.dropped} dropped', style('warn'))
    return text


def publish_toolbar(nav: NavState, entry: TopicEntry, width: int) -> Text:
    """Publish once, repeat at the rate (typed in place after R), and how many the repeat sent."""
    repeat = entry.repeat
    editing = nav.editing_in(RATE)
    rate = edit_value(editing.value, editing.fresh) if editing else clickable(Text(
        rate_text(repeat.rate if repeat else entry.rate()), Style(underline=True)), ('verb', 'rate'))
    label = Text.assemble('■ Stop repeating at ' if repeat else '↻ Repeat at ', rate, ' Hz')
    left = Text.assemble(button('▶ Publish once', 'primary', primary_look(nav, entry.tab, 'pri')), ' ',
                         button(label, 'secondary' if repeat else 'repeat', 'stop' if repeat else ''), '  ')
    if editing:
        left.append(f"type a rate · {key_for('edit_keep', mode='insert')} keeps · {RATE_RANGE}", style('dim'))
    else:
        left.append_text(hint(entry.rate_note(), (key_for('verb', 'rate'), 'changes it'), color='dim'))
    if repeat:
        left.append(f'  {repeat.sent(nav.feedback.clock())} sent', style('ok'))
    return spread(left, keyed(HISTORY_KEYS, 'earlier messages', 'dim'), width, optional=True)


def latest_panel(nav: NavState, entry: TopicEntry, area: Area) -> Panel:
    """LATEST MESSAGE: live, frozen while the cursor is inside it, or not echoing."""
    panel = Panel(area.title, aside=echo_counts(entry), hint=_echo_hint(nav, entry))
    if entry.editor is None:
        panel.lines = waiting(entry.error)
        return panel
    rows = entry.echo_rows(nav)
    width = column_width((row.field for row in rows), KEY_WIDTH)
    nobody = entry.publishers(nav) == 0
    for row in rows:
        shown = row.field not in entry.hidden
        line = Text.assemble('[x] ' if shown else '[ ] ', (row.field.ljust(width), style('syn-key')))
        line.append_text(_echo_value(entry, row, nobody) if shown else Text('hidden', style('dim')))
        panel.lines.append(line)
    panel.cursor = nav.row_index(area) if rows else None
    return panel


def _echo_hint(nav: NavState, entry: TopicEntry) -> Text:
    """LATEST MESSAGE's title hint: not echoing, frozen (with how many came in since) or live."""
    if entry.echo is None:
        return hint('not echoing', (key_for('primary'), 'starts'))
    if entry.frozen(nav):
        return Text.assemble(pill('❄ FROZEN', 'warn'), ' ', (f'+{entry.new_since} new since', style('warn')), '  ',
                             hint((key_for('go_up'), 'goes live'), (key_for('go_down'), 'shows / hides a field')))
    return Text.assemble(('● live', style('ok')), ' · ', hint((key_for('go_down'), 'freezes it')))


def _echo_value(entry: TopicEntry, row: Row, nobody: bool) -> Text:
    """A shown field's value in LATEST MESSAGE: – while not echoing, why nothing came yet (`nobody`:
    no publisher), else the value."""
    if entry.echo is None:
        return Text('–', style('dim'))
    if row.value is None:
        return Text('waiting — nobody publishes this yet' if nobody else 'waiting for the first message…', style('dim'))
    return shown_value(row)


def topic_panels(nav: NavState, entry: TopicEntry) -> list[Panel]:
    """LATEST MESSAGE (Echo) or MESSAGE (Publish), as the entry's one area."""
    return [latest_panel(nav, entry, area) if area.id == OUT else editor_panel(nav, entry, area)
            for area in entry.areas()]
