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

"""Unit tests: the bridge's bounded entity cache, with plain objects for entities."""

import pytest
from ros_tui.ros.entity_cache import EntityCache


class World:
    def __init__(self, size=2):
        self.busy = set()
        self.destroyed = []
        self.cache = EntityCache(size, lambda entity: entity in self.busy, self.destroy)

    def destroy(self, entity):
        self.destroyed.append(entity)

    def get(self, key):
        return self.cache.get(key, lambda: f'{key} entity')


@pytest.fixture
def world():
    return World()


def test_a_key_is_made_once_and_then_reused(world):
    made = []
    first = world.cache.get('a', lambda: made.append('a') or 'a entity')
    again = world.cache.get('a', lambda: made.append('a') or 'other')
    assert first == again == 'a entity' and made == ['a']


def test_over_size_the_least_recently_used_entity_is_destroyed(world):
    world.get('a')
    world.get('b')
    world.get('a')  # 'a' is now the most recent.
    world.get('c')
    assert world.destroyed == ['b entity']
    world.get('b')  # Made again: it was gone.
    assert world.destroyed == ['b entity', 'a entity']


def test_a_busy_entity_is_never_evicted(world):
    world.get('a')
    world.get('b')
    world.busy.add('a entity')
    world.get('c')
    assert world.destroyed == ['b entity']


def test_when_all_older_entities_are_busy_the_cache_grows_then_shrinks(world):
    """The entity just made is never the victim: it is handed out, so destroying it would
    break the call it was made for."""
    world.get('a')
    world.get('b')
    world.busy.update({'a entity', 'b entity'})
    assert world.get('c') == 'c entity'
    world.busy.add('c entity')
    assert world.get('d') == 'd entity'
    assert world.destroyed == []
    world.busy.clear()
    world.get('e')
    assert world.destroyed == ['a entity', 'b entity', 'c entity']


def test_a_failing_destroy_still_evicts(world):
    def broken(entity):
        world.destroyed.append(entity)
        raise RuntimeError('node gone')

    cache = EntityCache(1, lambda entity: False, broken)
    cache.get('a', lambda: 'a entity')
    assert cache.get('b', lambda: 'b entity') == 'b entity'
    assert world.destroyed == ['a entity']
    assert cache.get('a', lambda: 'a again') == 'a again'


def test_destroy_all_destroys_busy_entities_too(world):
    world.get('a')
    world.get('b')
    world.busy.add('a entity')
    world.cache.destroy_all()
    assert world.destroyed == ['a entity', 'b entity']
    world.get('a')  # Empty again: made anew.
    assert world.destroyed == ['a entity', 'b entity']
