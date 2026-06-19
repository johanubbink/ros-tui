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

"""The ros_tui visual identity: one dark theme anchored on the ROS-blue hue.

See ``docs/STYLE_GUIDE.md`` for the design rationale. The short version: a strict
two-tier colour system — one saturated blue (``$primary``) for *interaction and focus*
(the draggable seam, the focused-pane border, the active tab, the primary action button,
the selection), and green / amber / rose reserved for *operation outcomes* (success /
warning·streaming / error), which appear only in the status strip and output log. Every
other surface is one of three quiet blue-grey neutrals.

All colour in the app must come from theme variables, never hardcoded hex — that is what
keeps ``ctrl+p → change theme`` working and the look consistent.
"""

from textual.theme import Theme

# The one bold colour: interaction / focus. A bright, legible member of the ROS-blue hue
# family (the brand's #22314E is too dark to use literally on a dark canvas). Single-sourced
# here so the seam, focus border, active tab, primary button, and footer keys never drift.
ACCENT = '#4DA3FF'

# Secondary text (placeholders, type names, idle status) uses the theme's auto-derived
# ``$text-muted``; the design's reference muted tone is #8A93A8 (see docs/STYLE_GUIDE.md).

ROS_DARK = Theme(
    name='ros-dark',
    primary=ACCENT,
    accent=ACCENT,
    secondary='#7C8CC4',
    # Three quiet neutrals: canvas -> panels -> highest layer (selection, modal layering).
    background='#161922',
    surface='#1E2230',
    panel='#2A3042',
    foreground='#C8D0E0',
    # Operation outcomes — separated by both hue and luminance (not the fragile red/green
    # axis) and always paired with a glyph (see ros_tui/ui/styles.py) for colour-blind
    # and no-colour-terminal safety.
    success='#4EBF71',
    warning='#E5A33B',
    error='#F2607B',
    dark=True,
    variables={
        'block-cursor-text-style': 'none',            # selection highlight: no reverse-bold
        'footer-key-foreground': ACCENT,              # footer keybinds in the seam-blue
        'input-selection-background': f'{ACCENT} 30%',
    },
)
