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

"""
A bounded cache of ROS entities (clients, publishers) that never evicts a busy one.

Pure: no rclpy import. The bridge passes in how to tell an entity is busy and how to destroy
it; this module decides which entity goes when the cache is full. Not thread-safe: the bridge
uses it on the ROS thread only.
"""

import contextlib
from collections import OrderedDict
from typing import Any, Callable, Hashable


class EntityCache:
    """Entities by key, evicting the least recently used idle one once over ``size``.

    The entity ``get`` just made is never the victim. When every other entity is busy the
    cache grows past ``size`` rather than break a call; it shrinks again on a later ``get``
    once some are idle.
    """

    def __init__(self, size: int, busy: Callable[[Any], bool], destroy: Callable[[Any], None]):
        self._size = size
        self._busy = busy
        self._destroy = destroy
        self._entities: OrderedDict = OrderedDict()

    def get(self, key: Hashable, create: Callable[[], Any]) -> Any:
        """The entity under ``key``, made by ``create()`` if there is none yet."""
        if key in self._entities:
            self._entities.move_to_end(key)
            return self._entities[key]
        entity = create()
        self._entities[key] = entity
        while len(self._entities) > self._size:
            victim = next(
                (k for k, e in self._entities.items() if k != key and not self._busy(e)), None
            )
            if victim is None:
                break
            with contextlib.suppress(Exception):
                self._destroy(self._entities.pop(victim))
        return entity

    def destroy_all(self) -> None:
        """Destroy every entity, busy or not, and empty the cache; stops at the first error."""
        entities = list(self._entities.values())
        self._entities.clear()
        for entity in entities:
            self._destroy(entity)
