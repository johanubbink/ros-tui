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

Supports graph discovery, topic echo/publish, service calls and node parameters — each gated
on the server's advertised capabilities via ``features`` (so unsupported tabs/controls are
hidden). Actions have no place in the Foxglove protocol and are always off.
"""

import asyncio
import json
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass

import websockets
import yaml
from websockets.exceptions import InvalidStatus

from ros_tui.constants import RESPONSE_TIMEOUT_S
from ros_tui.contracts import BackendFeatures
from ros_tui.foxglove import protocol
from ros_tui.foxglove.codec import FoxgloveCodec
from ros_tui.foxglove.typestore import (
    FoxgloveTypestore,
    normalize_typename,
    service_message_typename,
)
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
_CDR = 'cdr'
_TIME_TYPE = 'builtin_interfaces/msg/Time'


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

        # Write path (publish / periodic / service calls).
        self._client_channels: dict[str, int] = {}  # topic -> client channel id
        self._next_client_channel = 1
        self._periodic: dict[str, object] = {}  # topic -> asyncio.Task
        # service name -> (service id, request typename, response typename)
        self._service_by_name: dict[str, tuple[int, str, str]] = {}
        self._pending_calls: dict[int, tuple] = {}  # call id -> (future, response typename)
        self._next_call_id = 1

        # Parameters (Foxglove params are global; we filter to a node by name prefix).
        self._pending_params: dict[str, object] = {}  # request id -> asyncio.Future
        self._next_param_id = 1
        self._param_prefix: dict[str, str] = {}  # node name -> discovered param-name prefix

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
                f'could not connect to foxglove bridge at {self._url}: '
                f'{_describe_connect_error(self._startup_error)}'
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
            self._url, subprotocols=list(protocol.SUBPROTOCOLS), max_size=None
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
        elif isinstance(message, protocol.ServiceCallResponse):
            pending = self._pending_calls.pop(message.call_id, None)
            if pending is None:
                return
            future, response_type = pending
            if future.done():
                return
            try:
                future.set_result(self.codec.deserialize(response_type, message.payload))
            except Exception as error:  # noqa: BLE001 - surface decode failure to the caller
                future.set_exception(error)

    # ---------------------------------------------------------------- inbound: JSON

    def _on_json(self, raw: str) -> None:
        message = json.loads(raw)
        handler = getattr(self, f'_on_{message.get("op", "")}', None)
        if handler is not None:
            handler(message)

    def _on_serverInfo(self, message: dict) -> None:
        caps = set(message.get('capabilities', []))
        self._has_connection_graph = 'connectionGraph' in caps
        # actions are never supported (no protocol support); parameters stay off until Phase 3.
        self.features = BackendFeatures(
            actions=False,
            services='services' in caps,
            parameters='parameters' in caps,
            connection_graph=self._has_connection_graph,
            publish='clientPublish' in caps,
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
            name = service['name']
            type_name = service.get('type', '')
            self._services[service['id']] = (name, type_name)
            self._register_service(service, name, type_name)
        self._rebuild_graph()

    def _register_service(self, service: dict, name: str, type_name: str) -> None:
        if not type_name:
            return
        request_key = service_message_typename(type_name, 'Request')
        response_key = service_message_typename(type_name, 'Response')
        request_type = self._register_service_side(service, 'request', request_key)
        response_type = self._register_service_side(service, 'response', response_key)
        if request_type and response_type:
            self._service_by_name[name] = (service['id'], request_type, response_type)

    def _register_service_side(self, service: dict, side: str, typename: str) -> str:
        """Register one side's schema (preferred ``request``/``response`` object, else legacy
        ``requestSchema``/``responseSchema`` string). Returns the typename, or '' if unusable."""
        block = service.get(side)
        if isinstance(block, dict):
            if block.get('schemaEncoding', 'ros2msg') != _ROS2_MSG or not block.get('schema'):
                return ''
            schema = block['schema']
        else:
            schema = service.get(f'{side}Schema')  # legacy string form
            if not schema:
                return ''
        try:
            return self._typestore.register_ros2msg(typename, schema)
        except Exception:  # noqa: BLE001 - unusable schema: service just can't be called
            return ''

    def _on_unadvertiseServices(self, message: dict) -> None:
        for service_id in message.get('serviceIds', []):
            entry = self._services.pop(service_id, None)
            if entry is not None:
                self._service_by_name.pop(entry[0], None)
        self._rebuild_graph()

    def _on_parameterValues(self, message: dict) -> None:
        future = self._pending_params.get(message.get('id'))
        if future is not None and not future.done():
            future.set_result(message.get('parameters', []))

    def _on_serviceCallFailure(self, message: dict) -> None:
        pending = self._pending_calls.pop(message.get('callId'), None)
        if pending is None:
            return
        future, _response_type = pending
        if not future.done():
            future.set_exception(RuntimeError(message.get('message', 'service call failed')))

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
        if not self.features.parameters:
            on_done(None, 'the server does not support parameters')
            return
        _relay(self._submit(self._list_params(node_name)), lambda r: on_done(r, None), on_done)

    def set_node_parameter(self, node_name: str, name: str, value_yaml: str, on_done) -> None:
        if not self.features.parameters:
            on_done('the server does not support parameters')
            return
        _relay(
            self._submit(self._set_param(node_name, name, value_yaml)),
            lambda _r: on_done(None),
            lambda error: on_done(error),
        )

    async def _list_params(self, node_name: str) -> list:
        values = await self._request_parameters([])  # empty list = every parameter
        prefix, params = self._filter_node_params(node_name, values)
        self._param_prefix[node_name] = prefix
        return params

    async def _set_param(self, node_name: str, name: str, value_yaml: str) -> None:
        value = yaml.safe_load(value_yaml)
        prefix = self._param_prefix.get(node_name) or f'{node_name.lstrip("/")}.'
        req_id = self._new_param_id()
        future = self._loop.create_future()
        self._pending_params[req_id] = future
        await self._ws.send(
            protocol.set_parameters_msg([_to_foxglove_param(prefix + name, value)], req_id)
        )
        try:
            await asyncio.wait_for(future, RESPONSE_TIMEOUT_S)
        except asyncio.TimeoutError as error:
            raise TimeoutError(f'no acknowledgement setting {name}') from error
        finally:
            self._pending_params.pop(req_id, None)

    async def _request_parameters(self, names: list) -> list:
        req_id = self._new_param_id()
        future = self._loop.create_future()
        self._pending_params[req_id] = future
        await self._ws.send(protocol.get_parameters_msg(names, req_id))
        try:
            return await asyncio.wait_for(future, RESPONSE_TIMEOUT_S)
        except asyncio.TimeoutError as error:
            raise TimeoutError('no response listing parameters') from error
        finally:
            self._pending_params.pop(req_id, None)

    def _filter_node_params(self, node_name: str, values: list) -> tuple[str, list]:
        # Foxglove parameter names are global and node-prefixed; the exact prefix
        # (leading slash or not) varies by bridge, so try both and keep what matches.
        for prefix in (f'{node_name.lstrip("/")}.', f'{node_name}.'):
            matches = [p for p in values if p.get('name', '').startswith(prefix)]
            if matches:
                params = [_param_tuple(p['name'][len(prefix):], p) for p in matches]
                return prefix, params
        return f'{node_name.lstrip("/")}.', []

    def _new_param_id(self) -> str:
        req_id = f'p{self._next_param_id}'
        self._next_param_id += 1
        return req_id

    # ---------------------------------------------------------------- topics: publish

    def publish_once(self, name, type_name, message, time_setters=()) -> Future:
        return self._submit(self._publish_once(name, message, time_setters))

    async def _publish_once(self, name, message, time_setters) -> None:
        channel_id = await self._ensure_client_channel(name, message.__msgtype__)
        self._apply_time_setters(time_setters)
        await self._ws.send(protocol.encode_client_message(channel_id, self.codec.serialize(message)))

    def start_periodic_publish(self, name, type_name, message, rate_hz, time_setters=()) -> Future:
        return self._submit(self._start_periodic(name, message, rate_hz, time_setters))

    async def _start_periodic(self, name, message, rate_hz, time_setters) -> None:
        channel_id = await self._ensure_client_channel(name, message.__msgtype__)
        existing = self._periodic.pop(name, None)
        if existing is not None:
            existing.cancel()
        period = 1.0 / rate_hz
        self._periodic[name] = asyncio.ensure_future(
            self._publish_loop(channel_id, message, period, time_setters)
        )

    async def _publish_loop(self, channel_id, message, period, time_setters) -> None:
        try:
            while True:
                self._apply_time_setters(time_setters)
                await self._ws.send(
                    protocol.encode_client_message(channel_id, self.codec.serialize(message))
                )
                await asyncio.sleep(period)
        except asyncio.CancelledError:
            pass

    def stop_periodic_publish(self, name) -> Future:
        return self._submit(self._stop_periodic(name))

    async def _stop_periodic(self, name) -> None:
        task = self._periodic.pop(name, None)
        if task is not None:
            task.cancel()

    async def _ensure_client_channel(self, name: str, typename: str) -> int:
        channel_id = self._client_channels.get(name)
        if channel_id is not None:
            return channel_id
        channel_id = self._next_client_channel
        self._next_client_channel += 1
        self._client_channels[name] = channel_id
        await self._ws.send(
            protocol.client_advertise_msg(
                [{'id': channel_id, 'topic': name, 'encoding': _CDR, 'schemaName': typename}]
            )
        )
        return channel_id

    # ---------------------------------------------------------------- services

    def call_service(self, name, type_name, request, time_setters=()) -> Future:
        return self._submit(self._call_service(name, request, time_setters))

    async def _call_service(self, name, request, time_setters):
        info = self._service_by_name.get(name)
        if info is None:
            raise RuntimeError(f'service {name} is not available (no ros2msg schema advertised)')
        service_id, _request_type, response_type = info
        self._apply_time_setters(time_setters)
        payload = self.codec.serialize(request)
        call_id = self._next_call_id
        self._next_call_id += 1
        future = self._loop.create_future()
        self._pending_calls[call_id] = (future, response_type)
        await self._ws.send(
            protocol.encode_service_call_request(service_id, call_id, _CDR, payload)
        )
        try:
            return await asyncio.wait_for(future, RESPONSE_TIMEOUT_S)
        except asyncio.TimeoutError as error:
            raise TimeoutError(
                f'no response from service {name} within {RESPONSE_TIMEOUT_S:.0f}s'
            ) from error
        finally:
            self._pending_calls.pop(call_id, None)

    def _apply_time_setters(self, time_setters) -> None:
        if not time_setters:
            return
        now = self._now_time()
        for setter in time_setters:
            setter(now)

    def _now_time(self):
        nanoseconds = self._server_time_ns if self._server_time_ns is not None else time.time_ns()
        sec, nanosec = divmod(nanoseconds, 1_000_000_000)
        return self._typestore.message_class(_TIME_TYPE)(sec=int(sec), nanosec=int(nanosec))

    # ---------------------------------------------------------------- actions (unsupported)

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


def _failed_future(message: str) -> Future:
    future: Future = Future()
    future.set_exception(RuntimeError(message))
    return future


def _relay(future: Future, on_success, on_error) -> None:
    """Bridge a concurrent.futures.Future to the (result)/(error-string) callback contract."""

    def done(finished: Future) -> None:
        try:
            on_success(finished.result())
        except Exception as error:  # noqa: BLE001 - reported to the UI as text
            on_error(str(error) or type(error).__name__)

    future.add_done_callback(done)


def _param_tuple(bare_name: str, param: dict) -> tuple:
    """A Foxglove parameter -> the (name, type_label, value) tuple the Nodes tab expects."""
    return (bare_name, _param_type_label(param.get('value'), param.get('type')), param.get('value'))


def _param_type_label(value, ptype) -> str:
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'double'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        if ptype == 'byte_array':
            return 'byte[]'
        if not value:
            return 'array'
        first = value[0]
        for kind, label in ((bool, 'bool[]'), (int, 'int[]'), (float, 'double[]'), (str, 'string[]')):
            if isinstance(first, kind):
                return label
    return ptype or 'unknown'


def _to_foxglove_param(name: str, value) -> dict:
    param = {'name': name, 'value': value}
    if isinstance(value, float):
        param['type'] = 'float64'
    elif isinstance(value, list) and value and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    ):
        param['type'] = 'float64_array'
    return param


def _normalize_url(url: str) -> str:
    if '://' not in url:
        return f'ws://{url}'
    return url


def _describe_connect_error(error: BaseException) -> str:
    """A readable reason for a failed connect, surfacing the server's HTTP-reject body.

    ``foxglove_bridge`` explains a rejected handshake in the 400 body (e.g. an unsupported
    subprotocol), which ``str(InvalidStatus)`` drops — so extract it.
    """
    if isinstance(error, InvalidStatus):
        response = error.response
        body = bytes(response.body or b'').decode('utf-8', 'replace').strip()
        detail = f'HTTP {response.status_code}'
        return f'{detail} — {body}' if body else detail
    return str(error) or type(error).__name__
