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

"""A thread-safe rosbags type store populated from the schemas the server advertises.

Wraps a ``rosbags`` typestore so message types can be registered from ``ros2msg`` schema text
and CDR-(de)serialized with no ROS install. The WebSocket thread registers types as channels
are advertised while the UI thread reads them (defaults/render/build), hence the lock.
"""

import threading

from rosbags.typesys import Stores, get_types_from_msg, get_typestore

from ros_tui.foxglove.protocol import split_ros2_schema


def normalize_typename(name: str, interface: str = 'msg') -> str:
    """Canonicalize a type string to the 3-part ``pkg/<interface>/Type`` rosbags key.

    Foxglove ROS 2 schema names are already 3-part; this tolerates a 2-part ``pkg/Type``.
    """
    parts = name.split('/')
    if len(parts) == 2:
        return f'{parts[0]}/{interface}/{parts[1]}'
    return name


def service_message_typename(type_name: str, side: str) -> str:
    """rosbags key for a service's request/response message (``side`` is 'Request'/'Response').

    rosbags only models *messages* and mangles any non-``msg`` interface path (it would turn
    ``pkg/srv/Foo_Request`` into ``pkg/srv/msg/Foo_Request``), so we synthesize the request and
    response types in the ``msg`` namespace: ``pkg/srv/Foo`` -> ``pkg/msg/Foo_Request``.
    """
    parts = type_name.split('/')
    return f'{parts[0]}/msg/{parts[-1]}_{side}'


class FoxgloveTypestore:
    """Holds every type the session has seen and does the CDR conversions."""

    def __init__(self):
        # Seed with a recent ROS 2 store so well-known types (Header, Time, …) are available
        # even if a schema omits a dependency; advertised schemas add everything else.
        self._store = get_typestore(Stores.ROS2_JAZZY)
        self._lock = threading.Lock()

    def register_ros2msg(self, schema_name: str, schema_text: str) -> str:
        """Register a channel/service schema; returns the root rosbags typename.

        Idempotent per type: fragments already known (from the base store or a prior advertise)
        are skipped, so re-advertising a channel or a shared dependency is cheap and conflict-
        free.
        """
        root = normalize_typename(schema_name)
        with self._lock:
            collected: dict = {}
            for name, body in split_ros2_schema(root, schema_text):
                name = normalize_typename(name)
                if name in self._store.types or name in collected:
                    continue
                try:
                    collected.update(get_types_from_msg(body, name))
                except Exception:  # noqa: BLE001 - a malformed fragment must not kill the run
                    continue
            collected = {k: v for k, v in collected.items() if k not in self._store.types}
            if collected:
                self._store.register(collected)
        return root

    def has(self, typename: str) -> bool:
        with self._lock:
            return typename in self._store.types

    def fielddefs(self, typename: str):
        """(constants, fields) for ``typename``; fields are (name, (Nodetype, typeinfo))."""
        with self._lock:
            return self._store.fielddefs[typename]

    def message_class(self, typename: str):
        with self._lock:
            return self._store.types[typename]

    def deserialize(self, cdr: bytes, typename: str):
        with self._lock:
            return self._store.deserialize_cdr(cdr, typename)

    def serialize(self, message, typename: str) -> bytes:
        with self._lock:
            return bytes(self._store.serialize_cdr(message, typename))
