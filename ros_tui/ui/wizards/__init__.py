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

"""Context-aware "wizard" popups that fill a message field's YAML for the user.

A single wizard button / ``ctrl+w`` inspects the field on the editor's cursor line and, if that
field's type has a registered wizard, opens it. The wizard dismisses with the field's *value*
(plain dict/scalar); the tab renders it back into the editor block. The wizards are decoupled
from any one tab: the controller lives on ``InterfaceTab`` (``open_field_wizard``), so every
editor tab can reuse them.

Layers (imports flow downward, no cycles):

* ``editing``    — pure text helpers (cursor path, block range, render/replace); no textual.
* ``registry``   — the ``WIZARDS`` map, the ``@register`` decorator, and ``matched_wizard``.
* ``base``       — ``WizardScreen``, the shared modal shell (escape/Apply/Cancel/error/CSS).
* ``components`` — ``ModeForm``, a composed radio-mode + per-mode-rows widget.
* one module per wizard (``header``/``quaternion``/``time``/``enum``).

Adding a wizard:

1. Create ``wizards/<name>.py``: subclass ``WizardScreen``, set ``TITLE`` and ``PREFIX``,
   implement ``compose_body()`` (optionally composing a ``ModeForm``) and ``build_value()``,
   plus a ``_parse_*`` prefill helper.
2. Decorate the class with ``@register('pkg/Type')``.
3. Import it below so the decorator runs, and add unit tests (pure helpers + a
   ``matched_wizard`` resolution case).

Enabling wizards on another editor tab (e.g. Services/Actions):

* override ``_extra_prototype_data`` to return ``message_structure(kind, type_name)``;
* override ``wizard_action`` to call ``self.open_field_wizard()`` (plus any per-tab guard).
"""

from ros_tui.ui.wizards.base import WizardScreen
from ros_tui.ui.wizards.components import ModeForm
from ros_tui.ui.wizards.editing import (
    cursor_field_path,
    field_block_range,
    field_node_at,
    field_type_at,
    render_field_block,
    replace_block,
)
from ros_tui.ui.wizards.enum import EnumWizardPopup
from ros_tui.ui.wizards.header import HeaderWizardPopup, _parse_header
from ros_tui.ui.wizards.quaternion import (
    QuaternionWizardPopup,
    clean_quat,
    normalize_quat,
    quat_about_axis,
    quat_from_euler,
)
from ros_tui.ui.wizards.registry import WIZARDS, matched_wizard, register
from ros_tui.ui.wizards.time import (
    _WALLCLOCK_FORMAT,
    TimeWizardPopup,
    _parse_time,
    epoch_to_stamp,
    parse_wallclock,
    seconds_str_to_stamp,
    stamp_to_seconds_str,
)

__all__ = [
    'WizardScreen',
    'ModeForm',
    'WIZARDS',
    'register',
    'matched_wizard',
    'cursor_field_path',
    'field_block_range',
    'field_node_at',
    'field_type_at',
    'render_field_block',
    'replace_block',
    'EnumWizardPopup',
    'HeaderWizardPopup',
    'QuaternionWizardPopup',
    'TimeWizardPopup',
    'clean_quat',
    'normalize_quat',
    'quat_about_axis',
    'quat_from_euler',
    'epoch_to_stamp',
    'parse_wallclock',
    'seconds_str_to_stamp',
    'stamp_to_seconds_str',
]
