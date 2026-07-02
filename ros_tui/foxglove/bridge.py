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

"""A drop-in bridge that talks to a remote ``foxglove_bridge`` over WebSocket.

Mirrors the duck-typed contract the UI expects from ``RosBridge`` (see ``ros/bridge.py``): the
same 13 methods plus ``start()``/``shutdown()``, ``latest_graph``, ``codec`` and ``features``.
A single daemon thread runs an asyncio event loop that owns the WebSocket connection; UI calls
are marshalled onto that loop with ``run_coroutine_threadsafe`` (which yields the
``concurrent.futures.Future`` the UI already expects), and server callbacks fire on that loop's
thread — exactly the threading contract RosBridge provides.

Phase 1 (this file) is read-only: connect, discover the graph, and echo topics. Publishing,
service calls and parameters raise a clear "not yet supported" until Phases 2–3 fill them in;
the corresponding tabs/controls are gated off via ``features``.
"""

import asyncio
import json
import threading
from concurrent.futures import Future
from dataclasses import dataclass

import websockets

from ros_tui.contracts import BackendFeatures
from ros_tui.foxglove import protocol
from ros_tui.foxglove.codec import FoxgloveCodec
from ros_tui.foxglove.typestore import FoxgloveTypestore, normalize_typename
from ros_tui.ros.echo import EchoBuffer  # noqa: F401 - documents the buffer contract
from ros_tui.ros.events import ActionEvent, ActionEventKind
from ros_tui.ros.graph import (
    EMPTY_GRAPH,
    GraphSnapshot,
    InterfaceEntry,
    NodeInfo,
    _entries,
    is_builtin_service,
    is_hidden_name,
    split_node_name,
)

_CONNECT_TIMEOUT_S = 10.0
_ROS2_MSG = 'ros2msg'


@dataclass
class _Channel:
    topic: str
    typename: str  # rosbags key, e.g. 'std_msgs/msg/String'
    decodable: bool  # False when the schema was not ros2msg (echo would fail)


@dataclass
class _Subscription:
    sub_id: int
    channel_id: int
    typename: str
    buffer: object  # EchoBuffer; the bridge only calls .push(msg)


class FoxgloveBridge:
    """UI-agnostic facade over a Foxglove WebSocket connection."""

    def __init__(self, url: str):
        self._url = _normalize_url(url)
        self._typestore = FoxgloveTypestore()
        self.codec = FoxgloveCodec(self._typestore)
        # Real capabilities are learned from serverInfo; until Phases 2–3 land, the write/param
        # paths stay off regardless of what the server advertises.
        self.features = BackendFeatures(
            actions=False,
            services=False,
            parameters=False,
            connection_graph=False,
            publish=False,
        )

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._running = False

        # Graph state (mutated on the asyncio thread only).
        self._channels: dict[int, _Channel] = {}
        self._topic_to_channel: dict[str, int] = {}
        self._services: dict[int, tuple[str, str]] = {}  # id -> (name, type)
        self._pub_topics: dict[str, set] = {}
        self._sub_topics: dict[str, set] = {}
        self._graph_services: dict[str, set] = {}  # service name -> provider node ids
        self._version = 0
        self._has_connection_graph = False

        # Subscriptions.
        self._subs_by_id: dict[int, _Subscription] = {}
        self._subs_by_topic: dict[str, int] = {}
        self._next_sub_id = 1

        # Snapshots read from the UI thread; assigned atomically (whole-object swap).
        self._latest_graph: GraphSnapshot = EMPTY_GRAPH
        self._node_infos: dict[str, NodeInfo] = {}
        self._graph_listener = None
        self._server_time_ns: int | None = None

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name='foxglove-bridge', daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=_CONNECT_TIMEOUT_S):
            self._running = False
            raise RuntimeError(f'timed out connecting to foxglove bridge at {self._url}')
        if self._startup_error is not None:
            raise RuntimeError(
                f'could not connect to foxglove bridge at {self._url}: {self._startup_error}'
            )

    def shutdown(self, timeout_s: float = 3.0) -> None:
        self._running = False
        loop, ws = self._loop, self._ws
        if loop is not None and ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except RuntimeError:
                pass  # loop already stopped
        if self._thread is not None:
            self._thread.join(timeout_s)

    @property
    def latest_graph(self) -> GraphSnapshot:
        return self._latest_graph

    def set_graph_listener(self, listener) -> None:
        self._graph_listener = listener

    # ---------------------------------------------------------------- asyncio thread

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as error:  # noqa: BLE001 - surfaced to start() via _startup_error
            if not self._ready.is_set():
                self._startup_error = error
                self._ready.set()
        finally:
            self._running = False

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        async with websockets.connect(
            self._url, subprotocols=[protocol.SUBPROTOCOL], max_size=None
        ) as ws:
            self._ws = ws
            async for raw in ws:
                try:
                    if isinstance(raw, (bytes, bytearray)):
                        self._on_binary(bytes(raw))
                    else:
                        self._on_json(raw)
                except Exception:  # noqa: BLE001 - one bad frame must not drop the connection
                    continue

    # ---------------------------------------------------------------- inbound: binary

    def _on_binary(self, data: bytes) -> None:
        message = protocol.parse_server_binary(data)
        if isinstance(message, protocol.MessageData):
            sub = self._subs_by_id.get(message.subscription_id)
            if sub is None:
                return
            try:
                decoded = self.codec.deserialize(sub.typename, message.payload)
            except Exception:  # noqa: BLE001 - undecodable frame: drop it, keep echoing
                return
            sub.buffer.push(decoded)
        elif isinstance(message, protocol.TimeMessage):
            self._server_time_ns = message.timestamp

    # ---------------------------------------------------------------- inbound: JSON

    def _on_json(self, raw: str) -> None:
        message = json.loads(raw)
        handler = getattr(self, f'_on_{message.get("op", "")}', None)
        if handler is not None:
            handler(message)

    def _on_serverInfo(self, message: dict) -> None:
        caps = set(message.get('capabilities', []))
        self._has_connection_graph = 'connectionGraph' in caps
        # actions never (no protocol support); services/parameters/publish stay off until
        # Phases 2–3 implement them, even when the server advertises the capability.
        self.features = BackendFeatures(
            actions=False,
            services=False,
            parameters=False,
            connection_graph=self._has_connection_graph,
            publish=False,
        )
        if self._has_connection_graph:
            self._send_now(protocol.subscribe_connection_graph_msg())
        self._ready.set()

    def _on_advertise(self, message: dict) -> None:
        changed = False
        for channel in message.get('channels', []):
            changed = self._add_channel(channel) or changed
        if changed:
            self._rebuild_graph()

    def _add_channel(self, channel: dict) -> bool:
        channel_id = channel['id']
        topic = channel['topic']
        schema_name = channel.get('schemaName', '')
        decodable = channel.get('schemaEncoding') == _ROS2_MSG and bool(channel.get('schema'))
        typename = normalize_typename(schema_name) if schema_name else ''
        if decodable:
            try:
                typename = self._typestore.register_ros2msg(schema_name, channel['schema'])
            except Exception:  # noqa: BLE001 - unparseable schema: list topic, mark undecodable
                decodable = False
        self._channels[channel_id] = _Channel(topic, typename, decodable)
        self._topic_to_channel[topic] = channel_id
        return True

    def _on_unadvertise(self, message: dict) -> None:
        changed = False
        for channel_id in message.get('channelIds', []):
            channel = self._channels.pop(channel_id, None)
            if channel is not None:
                self._topic_to_channel.pop(channel.topic, None)
                changed = True
        if changed:
            self._rebuild_graph()

    def _on_advertiseServices(self, message: dict) -> None:
        for service in message.get('services', []):
            self._services[service['id']] = (service['name'], service.get('type', ''))
        self._rebuild_graph()

    def _on_unadvertiseServices(self, message: dict) -> None:
        for service_id in message.get('serviceIds', []):
            self._services.pop(service_id, None)
        self._rebuild_graph()

    def _on_connectionGraphUpdate(self, message: dict) -> None:
        for topic in message.get('publishedTopics', []):
            self._pub_topics[topic['name']] = set(topic.get('publisherIds', []))
        for topic in message.get('subscribedTopics', []):
            self._sub_topics[topic['name']] = set(topic.get('subscriberIds', []))
        for service in message.get('advertisedServices', []):
            self._graph_services[service['name']] = set(service.get('providerIds', []))
        for name in message.get('removedTopics', []):
            self._pub_topics.pop(name, None)
            self._sub_topics.pop(name, None)
        for name in message.get('removedServices', []):
            self._graph_services.pop(name, None)
        self._rebuild_graph()

    # ---------------------------------------------------------------- graph assembly

    def _rebuild_graph(self) -> None:
        topics = _entries((ch.topic, (ch.typename,)) for ch in self._channels.values())
        services = _entries(
            ((name, (type_name,)) for name, type_name in self._services.values()),
            skip=is_builtin_service,
        )
        nodes = self._node_entries()
        self._version += 1
        self._latest_graph = GraphSnapshot(
            version=self._version, actions=(), services=services, topics=topics, nodes=nodes
        )
        self._node_infos = self._build_node_infos()
        listener = self._graph_listener
        if listener is not None:
            listener(self._latest_graph)

    def _node_entries(self) -> tuple[InterfaceEntry, ...]:
        names = set(self._pub_topics.keys()) | set(self._sub_topics.keys())
        node_ids: set[str] = set()
        for ids in list(self._pub_topics.values()) + list(self._sub_topics.values()):
            node_ids |= ids
        for ids in self._graph_services.values():
            node_ids |= ids
        entries = []
        for full in sorted(node_ids):
            if is_hidden_name(full):
                continue
            _name, namespace = split_node_name(full)
            entries.append(InterfaceEntry(full, (namespace,)))
        return tuple(entries)

    def _build_node_infos(self) -> dict[str, NodeInfo]:
        topic_type = {ch.topic: ch.typename for ch in self._channels.values()}
        service_type = {name: type_name for name, type_name in self._services.values()}
        node_ids: set[str] = set()
        for ids in list(self._pub_topics.values()) + list(self._sub_topics.values()):
            node_ids |= ids
        for ids in self._graph_services.values():
            node_ids |= ids

        infos: dict[str, NodeInfo] = {}
        for node in node_ids:
            pubs = [(t, (topic_type.get(t, ''),)) for t, ids in self._pub_topics.items() if node in ids]
            subs = [(t, (topic_type.get(t, ''),)) for t, ids in self._sub_topics.items() if node in ids]
            srvs = [
                (s, (service_type.get(s, ''),))
                for s, ids in self._graph_services.items()
                if node in ids
            ]
            infos[node] = NodeInfo(
                node_name=node,
                publishers=_entries(pubs),
                subscribers=_entries(subs),
                service_servers=_entries(srvs, skip=is_builtin_service),
                service_clients=(),
                action_servers=(),
                action_clients=(),
            )
        return infos

    # ---------------------------------------------------------------- topics: subscribe/echo

    def subscribe(self, name: str, type_name: str, buffer) -> Future:
        return self._submit(self._subscribe(name, buffer))

    async def _subscribe(self, name: str, buffer) -> None:
        channel_id = self._topic_to_channel.get(name)
        if channel_id is None:
            raise RuntimeError(f'topic {name} is not advertised by the server')
        channel = self._channels[channel_id]
        if not channel.decodable:
            raise RuntimeError(f'{name}: schema for {channel.typename or "topic"} is not ros2msg')
        # Replace any existing subscription so a fresh EchoBuffer is wired.
        old = self._subs_by_topic.get(name)
        if old is not None:
            self._subs_by_id.pop(old, None)
            await self._ws.send(protocol.unsubscribe_msg([old]))
        sub_id = self._next_sub_id
        self._next_sub_id += 1
        self._subs_by_id[sub_id] = _Subscription(sub_id, channel_id, channel.typename, buffer)
        self._subs_by_topic[name] = sub_id
        await self._ws.send(protocol.subscribe_msg([{'id': sub_id, 'channelId': channel_id}]))

    def unsubscribe(self, name: str) -> Future:
        return self._submit(self._unsubscribe(name))

    async def _unsubscribe(self, name: str) -> None:
        sub_id = self._subs_by_topic.pop(name, None)
        if sub_id is None:
            return
        self._subs_by_id.pop(sub_id, None)
        await self._ws.send(protocol.unsubscribe_msg([sub_id]))

    # ---------------------------------------------------------------- nodes

    def get_node_info(self, node_name: str, on_done) -> None:
        info = self._node_infos.get(node_name)
        if info is None:
            on_done(None, f'no connection-graph information for {node_name}')
        else:
            on_done(info, None)

    def list_node_parameters(self, node_name: str, on_done) -> None:
        # Phase 3 implements getParameters; report honestly until then.
        on_done(None, 'parameters are not yet supported over the Foxglove backend')

    def set_node_parameter(self, node_name: str, name: str, value_yaml: str, on_done) -> None:
        on_done('parameters are not yet supported over the Foxglove backend')

    # ---------------------------------------------------------------- write path (Phases 2–3)

    def publish_once(self, name, type_name, message, time_setters=()) -> Future:
        return _failed_future('publishing over the Foxglove backend is not yet supported')

    def start_periodic_publish(self, name, type_name, message, rate_hz, time_setters=()) -> Future:
        return _failed_future('publishing over the Foxglove backend is not yet supported')

    def stop_periodic_publish(self, name) -> Future:
        return _resolved_future()

    def call_service(self, name, type_name, request, time_setters=()) -> Future:
        return _failed_future('service calls over the Foxglove backend are not yet supported')

    def send_goal(self, name, type_name, goal, on_event, time_setters=()) -> None:
        on_event(
            ActionEvent(name, ActionEventKind.ERROR, 'actions are not supported over Foxglove')
        )

    def cancel_goal(self, name: str) -> None:
        pass

    # ---------------------------------------------------------------- plumbing

    def _submit(self, coro) -> Future:
        loop = self._loop
        if loop is None or not self._running:
            return _failed_future('not connected to the foxglove bridge')
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def _send_now(self, text: str) -> None:
        """Fire-and-forget a JSON message from the asyncio thread."""
        if self._ws is not None:
            asyncio.ensure_future(self._ws.send(text))


def _resolved_future(result=None) -> Future:
    future: Future = Future()
    future.set_result(result)
    return future


def _failed_future(message: str) -> Future:
    future: Future = Future()
    future.set_exception(RuntimeError(message))
    return future


def _normalize_url(url: str) -> str:
    if '://' not in url:
        return f'ws://{url}'
    return url
