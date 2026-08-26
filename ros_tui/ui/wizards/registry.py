#!/usr/bin/env python3
# Copyright 2026 Jonas Vervoort
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

"""The wizard registry and the cursor→wizard lookup.

Wizards register themselves against a message type label with ``@register('pkg/Type')``; the
package ``__init__`` imports each wizard module so the decorators run. ``matched_wizard`` maps
the cursor's field path to the most specific popup to open.
"""

import functools
from typing import Any

from ros_tui.ui.wizards.editing import field_node_at

# Keyed by the type label from get_fields_and_field_types() (e.g. 'std_msgs/Header').
WIZARDS: dict[str, type] = {}


def register(type_label: str):
    """Class decorator: register a ``WizardScreen`` subclass for ``type_label``."""
    def decorator(cls):
        WIZARDS[type_label] = cls
        return cls
    return decorator


def matched_wizard(structure: Any, path: list[str]) -> tuple[list[str], Any] | None:
    """Innermost prefix of ``path`` that has a wizard, with a callable ``(current_value)`` factory.

    Walking deepest-first opens the most specific popup for where the cursor sits: on a
    ``header.stamp`` row the Time wizard wins, while on the ``header`` line (or a plain leaf
    like ``header.frame_id`` that has no wizard of its own) it falls back outward to the
    Header wizard. This generalises to any depth of nesting.

    A field matches either because its type is in ``WIZARDS`` (the factory is that class) or
    because it is an integer enum carrying ``constants`` (the factory is an ``EnumWizardPopup``
    pre-bound to those choices). Either way the caller just calls ``factory(current_value)``.
    """
    from ros_tui.ui.wizards.enum import EnumWizardPopup

    for depth in range(len(path), 0, -1):
        prefix = path[:depth]
        node = field_node_at(structure, prefix)
        if node is None:
            continue
        if node.type_label in WIZARDS:
            return prefix, WIZARDS[node.type_label]
        if node.constants:
            return prefix, functools.partial(EnumWizardPopup, choices=node.constants)
    return None
