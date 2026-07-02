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

"""Backend-neutral contracts shared by the UI and every bridge backend.

This module must stay free of any ROS import (rclpy / rosidl / message packages) so the UI
can run against a non-ROS backend (e.g. the Foxglove WebSocket client) on a machine with no
ROS install. A backend is a matched *(bridge, codec)* pair: the bridge speaks a transport,
the codec turns type strings + YAML into an opaque message payload and renders payloads back
to YAML. The UI reaches both through the bridge it already holds (``bridge.codec`` /
``bridge.features``), so nothing in the UI has to know which backend is live.
"""

from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

# A deferred setter that stamps a backend-native "now" Time into a message field (the
# ``stamp: now`` / ``header: auto`` magic). The argument type is a private contract between a
# codec and its bridge; the UI only ever passes the tuple through opaquely, and the bridge
# supplies the concrete Time when applying it right before sending.
TimeSetter = Callable[[Any], None]


class IntrospectionError(Exception):
    """Raised when an interface type cannot be loaded/resolved."""


class FieldError(Exception):
    """A value in the user's YAML does not fit the message, located by its field path."""

    def __init__(self, path: str, detail: str):
        self.path = path
        self.detail = detail
        super().__init__(f'{path}: {detail}' if path else detail)


@runtime_checkable
class MessageCodec(Protocol):
    """Turns interface types + YAML into an opaque payload and renders payloads back.

    ``kind`` is one of ``'msg'``, ``'srv'``, ``'action'``. The returned/accepted *payload* is
    opaque to the UI and specific to the backend (native: a rosidl message instance; foxglove:
    a rosbags message + typename); it is only ever handed straight back to the same backend's
    bridge or ``render``.
    """

    def default_yaml(self, kind: str, type_name: str) -> str:
        """Editor seed text: the default message as YAML plus an optional constants hint.

        May run on a worker thread. Raises :class:`IntrospectionError` on an unknown type.
        """
        ...

    def build(
        self, kind: str, type_name: str, values: Any
    ) -> tuple[Any, tuple[TimeSetter, ...]]:
        """Build a checked payload from ``yaml.safe_load`` output (dict / None / scalar).

        Runs synchronously on the UI thread so validation happens before dispatch. Returns the
        payload and the deferred time setters. Raises :class:`FieldError` on any value mismatch
        and :class:`IntrospectionError` on an unknown type.
        """
        ...

    def render(self, payload: Any) -> str:
        """Render a payload as display YAML, truncating long arrays/strings."""
        ...


@dataclass(frozen=True)
class BackendFeatures:
    """Which capabilities a backend supports, so the app can hide/disable what it can't do.

    The native rclpy backend sets all True; the Foxglove backend derives these from the
    server's advertised capabilities (and ``actions`` is always False — the protocol has no
    first-class action support).
    """

    actions: bool
    services: bool
    parameters: bool
    connection_graph: bool
    publish: bool
