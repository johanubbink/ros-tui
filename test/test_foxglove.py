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

"""Foxglove WebSocket backend tests.

These need no ROS: the protocol layer is pure stdlib, and the codec/bridge use the pure-Python
``rosbags`` + ``websockets`` packages. Tests that need those two skip cleanly when they are not
installed (the [foxglove] extra), so the native suite still runs on a bare ROS image.
"""

import json
import struct
import threading
import time

import pytest

from ros_tui.foxglove import protocol

pytestmark = pytest.mark.foxglove

STRING_TYPE = 'std_msgs/msg/String'


# ------------------------------------------------------------------ pure protocol (no deps)


def test_binary_framing_roundtrip():
    md = protocol.parse_server_binary(
        struct.pack('<BIQ', protocol.SERVER_MESSAGE_DATA, 7, 42) + b'\xde\xad'
    )
    assert (md.subscription_id, md.timestamp, md.payload) == (7, 42, b'\xde\xad')

    tm = protocol.parse_server_binary(struct.pack('<BQ', protocol.SERVER_TIME, 999))
    assert tm.timestamp == 999

    resp = struct.pack('<BIII', protocol.SERVER_SERVICE_CALL_RESPONSE, 3, 4, 3) + b'cdr' + b'ok'
    parsed = protocol.parse_server_binary(resp)
    assert (parsed.service_id, parsed.call_id, parsed.encoding, parsed.payload) == (3, 4, 'cdr', b'ok')

    assert protocol.encode_client_message(5, b'\x01') == struct.pack('<BI', 1, 5) + b'\x01'
    assert protocol.encode_service_call_request(3, 4, 'cdr', b'x') == (
        struct.pack('<BIII', 2, 3, 4, 3) + b'cdr' + b'x'
    )
    assert protocol.parse_server_binary(b'') is None


def test_split_ros2_schema_separates_dependencies():
    schema = (
        'std_msgs/Header header\n'
        'geometry_msgs/Point point\n'
        '================================================================================\n'
        'MSG: std_msgs/Header\n'
        'builtin_interfaces/Time stamp\n'
        'string frame_id\n'
        '================================================================================\n'
        'MSG: geometry_msgs/Point\n'
        'float64 x\n'
    )
    frags = protocol.split_ros2_schema('geometry_msgs/msg/PointStamped', schema)
    names = [name for name, _ in frags]
    assert names == ['geometry_msgs/msg/PointStamped', 'std_msgs/Header', 'geometry_msgs/Point']
    assert 'string frame_id' in dict(frags)['std_msgs/Header']


# ------------------------------------------------------------------ codec / typestore (rosbags)


def _string_schema():
    rosbags_ts = pytest.importorskip('rosbags.typesys')
    store = rosbags_ts.get_typestore(rosbags_ts.Stores.ROS2_JAZZY)
    return store, store.generate_msgdef(STRING_TYPE)[0]


def test_typestore_registers_schema_and_roundtrips_cdr():
    store, schema = _string_schema()
    from ros_tui.foxglove.typestore import FoxgloveTypestore

    ts = FoxgloveTypestore()
    root = ts.register_ros2msg(STRING_TYPE, schema)
    assert root == STRING_TYPE and ts.has(root)

    cdr = bytes(store.serialize_cdr(store.types[STRING_TYPE](data='hi'), STRING_TYPE))
    assert ts.deserialize(cdr, root).data == 'hi'


def test_codec_default_yaml_and_render():
    store, schema = _string_schema()
    from ros_tui.contracts import IntrospectionError
    from ros_tui.foxglove.codec import FoxgloveCodec
    from ros_tui.foxglove.typestore import FoxgloveTypestore

    ts = FoxgloveTypestore()
    ts.register_ros2msg(STRING_TYPE, schema)
    codec = FoxgloveCodec(ts)

    assert codec.default_yaml('msg', STRING_TYPE) == "data: ''\n"
    decoded = ts.deserialize(bytes(store.serialize_cdr(store.types[STRING_TYPE](data='hey'), STRING_TYPE)), STRING_TYPE)
    assert codec.render(decoded) == 'data: hey'
    with pytest.raises(IntrospectionError):
        codec.default_yaml('msg', 'nope/msg/Nope')


# ------------------------------------------------------------------ bridge (mock server)


def _wait_until(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_foxglove_bridge_discovers_graph_and_echoes():
    websockets = pytest.importorskip('websockets')
    rosbags_ts = pytest.importorskip('rosbags.typesys')
    import asyncio

    from ros_tui.foxglove.bridge import FoxgloveBridge
    from ros_tui.ros.echo import EchoBuffer

    store = rosbags_ts.get_typestore(rosbags_ts.Stores.ROS2_JAZZY)
    schema = store.generate_msgdef(STRING_TYPE)[0]

    async def handler(ws):
        await ws.send(json.dumps({
            'op': 'serverInfo', 'name': 'mock', 'capabilities': ['connectionGraph'],
            'supportedEncodings': ['cdr'], 'metadata': {}, 'sessionId': '1',
        }))
        await ws.send(json.dumps({'op': 'advertise', 'channels': [{
            'id': 10, 'topic': '/chatter', 'encoding': 'cdr',
            'schemaName': STRING_TYPE, 'schemaEncoding': 'ros2msg', 'schema': schema,
        }]}))
        await ws.send(json.dumps({
            'op': 'connectionGraphUpdate',
            'publishedTopics': [{'name': '/chatter', 'publisherIds': ['/talker']}],
            'subscribedTopics': [], 'advertisedServices': [],
            'removedTopics': [], 'removedServices': [],
        }))
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get('op') == 'subscribe':
                sub_id = msg['subscriptions'][0]['id']
                payload = bytes(store.serialize_cdr(store.types[STRING_TYPE](data='hello'), STRING_TYPE))
                await ws.send(struct.pack('<BIQ', 1, sub_id, 0) + payload)

    holder, ready = [], threading.Event()

    def run_server():
        async def main():
            server = await websockets.serve(
                handler, 'localhost', 0, subprotocols=[protocol.SUBPROTOCOL]
            )
            holder.append(server.sockets[0].getsockname()[1])
            ready.set()
            await asyncio.Future()

        asyncio.run(main())

    threading.Thread(target=run_server, daemon=True).start()
    assert ready.wait(5), 'mock server did not start'

    bridge = FoxgloveBridge(f'ws://localhost:{holder[0]}')
    bridge.start()
    try:
        assert bridge.features.connection_graph and not bridge.features.actions
        assert _wait_until(lambda: len(bridge.latest_graph.topics) == 1)
        graph = bridge.latest_graph
        assert graph.topics[0].name == '/chatter'
        assert graph.topics[0].types[0] == STRING_TYPE
        assert {n.name for n in graph.nodes} == {'/talker'}

        info = {}
        bridge.get_node_info('/talker', lambda i, e: info.update(info=i, err=e))
        assert [e.name for e in info['info'].publishers] == ['/chatter']

        buffer = EchoBuffer()
        bridge.subscribe('/chatter', STRING_TYPE, buffer).result(timeout=3)
        received = []

        def drained():
            messages, *_ = buffer.drain()
            received.extend(messages)
            return bool(received)

        assert _wait_until(drained, timeout=3), 'no echo message arrived'
        assert received[0].data == 'hello'
        assert bridge.codec.render(received[0]) == 'data: hello'
        bridge.unsubscribe('/chatter').result(timeout=3)
    finally:
        bridge.shutdown()
