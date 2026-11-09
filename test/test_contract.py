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

"""The bridge contract (ros_tui/ros/contract.py): RosBridge and FakeBridge both implement every
member with the same parameters, and the UI calls nothing on a bridge outside it."""

import inspect
import re
from pathlib import Path

import pytest
from harness.fake_bridge import FakeBridge
from ros_tui.ros.bridge import RosBridge
from ros_tui.ros.contract import Bridge

UI = Path(__file__).resolve().parents[1] / 'ros_tui' / 'ui'
MEMBERS = sorted(name for name in vars(Bridge) if not name.startswith('_'))
# `bridge.x` / `self._bridge.x` in the UI's code, but not a path such as `ros/bridge.py`.
BRIDGE_USE = re.compile(r'(?<![/\w])_?bridge\.([A-Za-z_]\w*)')


def _parameters(function) -> list[inspect.Parameter]:
    return list(inspect.signature(function).parameters.values())[1:]  # Without self.


@pytest.mark.parametrize('member', MEMBERS)
@pytest.mark.parametrize('implementation', [RosBridge, FakeBridge], ids=lambda cls: cls.__name__)
def test_implementation_has_the_member_with_its_parameters(implementation, member):
    spec = vars(Bridge)[member]
    if isinstance(spec, property):  # FakeBridge may hold it as a plain attribute.
        assert hasattr(implementation(), member)
        return
    actual = getattr(implementation, member, None)
    assert callable(actual), f'{implementation.__name__}.{member} is missing'
    wanted, got = _parameters(spec), _parameters(actual)
    assert [p.name for p in got[:len(wanted)]] == [p.name for p in wanted]
    for want, have in zip(wanted, got):
        assert want.default is inspect.Parameter.empty or have.default is not inspect.Parameter.empty, (
            f'{implementation.__name__}.{member}: {have.name} needs a default')
    extra = [p.name for p in got[len(wanted):] if p.default is inspect.Parameter.empty]
    assert not extra, f'{implementation.__name__}.{member} requires parameters the contract lacks: {extra}'


def test_the_ui_calls_only_contract_members_on_a_bridge():
    used = {(path.relative_to(UI).as_posix(), name)
            for path in UI.rglob('*.py') for name in BRIDGE_USE.findall(path.read_text())}
    assert len({name for _, name in used}) >= 10  # The pattern still finds the UI's calls.
    assert sorted(use for use in used if use[1] not in MEMBERS) == []
