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

"""One value as text (ros_tui/ui/values.py): shown as flow YAML, typed back, errors named."""

from ros_tui.ui.values import summary


def test_summaries():
    assert summary({'a': 19, 'b': 23}, 60) == 'a: 19, b: 23'
    assert summary({'data': 'x' * 100}, 20) == 'data: xxxxxxxxxxxxx…'
