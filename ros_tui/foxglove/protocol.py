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

"""Wire format for the ``foxglove.websocket.v1`` protocol: binary framing, JSON message
builders, and the ros2msg schema splitter.

This module is pure stdlib (struct/json/re) so it can be unit-tested without a live server,
websockets, or rosbags. All integers on the wire are little-endian.
"""

import json
import re
import struct
from dataclasses import dataclass

SUBPROTOCOL = 'foxglove.websocket.v1'

# Binary opcodes (first byte). Server->client and client->server reuse the low values but are
# disambiguated by direction.
SERVER_MESSAGE_DATA = 0x01
SERVER_TIME = 0x02
SERVER_SERVICE_CALL_RESPONSE = 0x03
SERVER_FETCH_ASSET_RESPONSE = 0x04

CLIENT_MESSAGE_DATA = 0x01
CLIENT_SERVICE_CALL_REQUEST = 0x02


@dataclass(frozen=True)
class MessageData:
    """A server->client message on a subscription (opcode 0x01)."""

    subscription_id: int
    timestamp: int  # nanoseconds
    payload: bytes  # CDR-encoded (includes the encapsulation header)


@dataclass(frozen=True)
class TimeMessage:
    """A server->client clock tick (opcode 0x02), sent when the server has the `time` cap."""

    timestamp: int  # nanoseconds


@dataclass(frozen=True)
class ServiceCallResponse:
    """A server->client service response (opcode 0x03)."""

    service_id: int
    call_id: int
    encoding: str
    payload: bytes


def parse_server_binary(data: bytes):
    """Parse a server->client binary frame into one of the dataclasses above.

    Returns ``None`` for opcodes we do not handle (e.g. fetch-asset responses), so callers can
    ignore them rather than crash.
    """
    if not data:
        return None
    op = data[0]
    if op == SERVER_MESSAGE_DATA:
        sub_id, timestamp = struct.unpack_from('<IQ', data, 1)
        return MessageData(sub_id, timestamp, data[13:])
    if op == SERVER_TIME:
        (timestamp,) = struct.unpack_from('<Q', data, 1)
        return TimeMessage(timestamp)
    if op == SERVER_SERVICE_CALL_RESPONSE:
        service_id, call_id, enc_len = struct.unpack_from('<III', data, 1)
        encoding = data[13 : 13 + enc_len].decode('utf-8')
        return ServiceCallResponse(service_id, call_id, encoding, data[13 + enc_len :])
    return None


def encode_client_message(channel_id: int, payload: bytes) -> bytes:
    """Frame a client->server published message (opcode 0x01)."""
    return struct.pack('<BI', CLIENT_MESSAGE_DATA, channel_id) + payload


def encode_service_call_request(
    service_id: int, call_id: int, encoding: str, payload: bytes
) -> bytes:
    """Frame a client->server service request (opcode 0x02)."""
    enc = encoding.encode('utf-8')
    header = struct.pack('<BIII', CLIENT_SERVICE_CALL_REQUEST, service_id, call_id, len(enc))
    return header + enc + payload


# ----------------------------------------------------------------- JSON message builders


def subscribe_msg(subscriptions: list[dict]) -> str:
    """subscriptions: [{'id': int, 'channelId': int}, ...]."""
    return json.dumps({'op': 'subscribe', 'subscriptions': subscriptions})


def unsubscribe_msg(subscription_ids: list[int]) -> str:
    return json.dumps({'op': 'unsubscribe', 'subscriptionIds': subscription_ids})


def client_advertise_msg(channels: list[dict]) -> str:
    """channels: [{'id': int, 'topic': str, 'encoding': str, 'schemaName': str}, ...]."""
    return json.dumps({'op': 'advertise', 'channels': channels})


def client_unadvertise_msg(channel_ids: list[int]) -> str:
    return json.dumps({'op': 'unadvertise', 'channelIds': channel_ids})


def get_parameters_msg(parameter_names: list[str], request_id: str) -> str:
    return json.dumps(
        {'op': 'getParameters', 'parameterNames': parameter_names, 'id': request_id}
    )


def set_parameters_msg(parameters: list[dict], request_id: str) -> str:
    return json.dumps({'op': 'setParameters', 'parameters': parameters, 'id': request_id})


def subscribe_connection_graph_msg() -> str:
    return json.dumps({'op': 'subscribeConnectionGraph'})


# ----------------------------------------------------------------- ros2msg schema splitting

# A separator line in a concatenated ros2msg definition: a run of '=' on its own line.
_SCHEMA_SEPARATOR = re.compile(r'^=+\s*$', re.MULTILINE)
_MSG_HEADER = re.compile(r'^MSG:\s*(\S+)\s*$')


def split_ros2_schema(root_name: str, schema_text: str) -> list[tuple[str, str]]:
    """Split a concatenated ``ros2msg`` schema into ``(typename, definition_body)`` fragments.

    Foxglove advertises a channel's schema as the root message definition followed by every
    dependency, each in a section introduced by a ``MSG: pkg/msg/Type`` line and separated by a
    line of ``=``. The first (headerless) section is the root type, named by ``root_name``.
    """
    fragments: list[tuple[str, str]] = []
    for index, section in enumerate(_SCHEMA_SEPARATOR.split(schema_text)):
        if index == 0:
            fragments.append((root_name, section.strip('\n')))
            continue
        lines = section.splitlines()
        name = None
        body_start = 0
        for line_no, line in enumerate(lines):
            match = _MSG_HEADER.match(line.strip())
            if match:
                name = match.group(1)
                body_start = line_no + 1
                break
        if name:
            fragments.append((name, '\n'.join(lines[body_start:]).strip('\n')))
    return fragments
