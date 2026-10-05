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

"""The colours of the new UI, in one place: the design's :root tokens and its KC kind table.

Widgets that build Rich text use `TOKENS`, `KINDS` and `MODES` directly; textual CSS gets the same
values as `$rt-<token>` variables (`css_variables`, merged in by the app). Don't put hex values in
widget code or CSS. The tokens are documented in docs/design-principles.md ("Colour tokens").
"""

from typing import NamedTuple

TOKENS = {
    # The design's :root.
    'term': '#121212',  # terminal background
    'term-2': '#181818',  # panel body
    'term-3': '#1e1e1e',  # panel title
    'tline': '#333333',  # panel border at rest
    'text': '#dcdcdc',  # terminal text
    'muted': '#7d8794',
    'faint': '#4d5662',
    'accent': '#3a96dd',  # entry names in headers
    'accent-fill': '#0178d4',  # primary buttons, the inside-an-area border, the ☰ tab underline
    'key': '#eceff4',  # key caps, the selected-panel border, the tab-row cursor
    'ok': '#89d185',
    'live': '#4fd8e8',
    'warn': '#ffd08a',
    'bad': '#f48771',
    # Surfaces and greys the design's terminal CSS uses.
    'top': '#1a1f26',  # the top bar
    'strip': '#141414',  # the tab row and the activity strip
    'foot': '#1b1b1b',  # the footer
    'rule': '#2a2a2a',  # the rule under the tab row
    'bright': '#ffffff',  # the active tab, the breadcrumb's last part
    'brand': '#e6e6e6',
    'label': '#cfcfcf',  # the ☰ tab, panel titles
    'grey': '#8a8a8a',  # tabs at rest, chips at rest
    'dim': '#5f5f5f',  # the .dim class: hints, empty states
    'head': '#6a6a6a',  # list headers, the breadcrumb, the search box text
    'number': '#5a5a5a',  # tab numbers
    'feed-head': '#5f6f7f',  # ACTIVITY · ALL TABS
    'type': '#5f8f99',  # the Type column
    'cursor': '#2b3a4a',  # the cursor row / the chip that is on
    'cursor-on': '#3a414c',  # the cursor row while the list has the keys
    'tab-on': '#1d1d1d',  # the active tab
    'tab-cur': '#262b33',  # the tab-row cursor, a selected panel's title
    'panel-in': '#16283a',  # the title of the panel you are inside
    'row-in': '#22303e',  # the current row inside a panel
    'sep': '#444444',  # the breadcrumb's › separators
    'mode-text': '#121212',  # text on a mode badge
}


class KindStyle(NamedTuple):
    glyph: str
    color: str
    tag_bg: str  # Background of the "≋ TOPIC" tag in an entry's header.
    label: str  # 'Topics'
    one: str  # 'topic'


# The design's KC table, by nav.KINDS.
KINDS = {
    'topics': KindStyle('≋', '#5fb3a8', '#14302c', 'Topics', 'topic'),
    'services': KindStyle('⇄', '#a597ea', '#241f3d', 'Services', 'service'),
    'actions': KindStyle('▷', '#d995b9', '#3a1f2f', 'Actions', 'action'),
    'nodes': KindStyle('◆', '#93a4b8', '#222a33', 'Nodes', 'node'),
}

# The footer's mode badge colours (dark text on them).
MODES = {
    'normal': '#6a8fb3',
    'insert': TOKENS['ok'],
    'helper': '#e6c07b',
    'search': '#c9d1d9',
    'command': '#c586c0',
}


def css_variables() -> dict[str, str]:
    """Every colour as a textual CSS variable: $rt-term, $rt-kind-topics, $rt-mode-normal …"""
    variables = {f'rt-{name}': value for name, value in TOKENS.items()}
    variables.update({f'rt-kind-{kind}': style.color for kind, style in KINDS.items()})
    variables.update({f'rt-mode-{mode}': color for mode, color in MODES.items()})
    return variables
