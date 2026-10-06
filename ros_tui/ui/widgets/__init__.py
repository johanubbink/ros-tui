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

"""The widgets. Each draws part of a `NavState` and decides nothing (see base.py)."""

from ros_tui.ui.widgets.activity_strip import ActivityStrip
from ros_tui.ui.widgets.command_suggestions import CommandSuggestions
from ros_tui.ui.widgets.entry_body import EntryBody
from ros_tui.ui.widgets.footer import Footer
from ros_tui.ui.widgets.helper_popup import HelperPopup
from ros_tui.ui.widgets.home_list import HomeList
from ros_tui.ui.widgets.log_popup import LogPopup
from ros_tui.ui.widgets.search_popup import SearchPopup
from ros_tui.ui.widgets.tab_row import EntryTabRow
from ros_tui.ui.widgets.toast import ToastView
from ros_tui.ui.widgets.top_bar import TopBar
from ros_tui.ui.widgets.which_key import WhichKeyPopup

__all__ = ['ActivityStrip', 'CommandSuggestions', 'EntryBody', 'EntryTabRow', 'Footer', 'HelperPopup', 'HomeList', 'LogPopup',
           'SearchPopup', 'ToastView', 'TopBar', 'WhichKeyPopup']
