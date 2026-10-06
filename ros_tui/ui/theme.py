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
    'panel-hint': '#9a9a9a',  # the hints in a panel's title bar
    'err-bg': '#201414',  # an errline under a panel
    'edit': '#1c2733',  # a value being typed
    'edit-fresh': '#2f4f73',  # a value the first typed key replaces (a bool)
    # Message rows (the design's .key .num .str .hint .ln).
    'syn-key': '#9cdcfe',  # field names
    'syn-num': '#b5cea8',  # numbers and bools
    'syn-str': '#ce9178',  # strings
    'syn-hint': '#5c6f5c',  # "# int64" type hints
    'line-no': '#4a4a4a',  # row numbers
    # Pills in panel titles (the design's .pill.run / .pill.can; .pill.ok is ok on ok-bg).
    'live-bg': '#0f3a40',
    'warn-bg': '#3a3010',
    # Buttons (the design's .btn, .btn.stop and .btn[disabled]; .btn.pri is bright on accent-fill).
    'btn': '#1f1f1f',
    'btn-text': '#e6e6e6',
    'stop-bg': '#4a2a12',
    'btn-off': '#5a5a5a',  # a disabled button's text and key (the design's .btn[disabled])
    'btn-off-bg': '#181818',
    'sep': '#444444',  # the breadcrumb's › separators
    'mode-text': '#121212',  # text on a mode badge
    # Overlays: search, which-key, :log, the command suggestions and toasts.
    'pop': '#1b222b',  # the search box
    'pop-2': '#161b22',  # the which-key popup, the :log view
    'pop-edge': '#6a8fb3',  # the which-key and :log border
    'pop-line': '#2c3743',  # rules inside a popup
    'pop-title': '#99aabb',  # the which-key title
    'cmd-bg': '#1d1a24',  # the command suggestions
    'cmd-edge': '#5a3f63',
    'cmd-sel': '#3a2a40',  # the picked suggestion
    'ok-bg': '#173a17',  # an ok toast (and ✓ OK pills)
    'bad-bg': '#3a1515',  # a bad toast
    'info': '#8fc3ec',  # an info toast's text, on panel-in
    # Field helpers (the design's .hb badge, .hpop popup and .comp enum completion).
    'hb-edge': '#4a5568',  # a row's [f …] badge at rest
    'hb-text': '#aab4c3',
    'hb-on': '#2a313b',  # the badge on the row under the cursor, the helper field being typed
    'help-field': '#6a7382',  # a helper field's underline colour, the popup's key hint line
    'comp': '#7f8a99',  # an enum's completion while typing it
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
