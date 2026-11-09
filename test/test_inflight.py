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

"""Unit tests: the bridge's requests in flight, on a hand-driven clock with fake entities."""

import pytest
from ros_tui.constants import READY_TIMEOUT_S, RESPONSE_TIMEOUT_S
from ros_tui.ros.events import ActionEventKind
from ros_tui.ros.inflight import Inflight


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeFuture:
    """A request future whose done callback fires only when the test says so."""

    def __init__(self, name='future'):
        self.name = name
        self.callbacks = []

    def add_done_callback(self, callback):
        self.callbacks.append(callback)

    def fire(self):
        for callback in self.callbacks:
            callback(self)


class FakeClient:
    def __init__(self):
        self.dropped = []

    def remove_pending_request(self, future):
        self.dropped.append(future.name)


class ActionClient:
    def __init__(self, up=True):
        self.up = up

    def server_is_ready(self):
        return self.up


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def inflight(clock):
    return Inflight(clock)


def test_a_wait_for_a_ready_server_dispatches_at_once(inflight):
    seen = []
    entity = object()
    inflight.wait_for_server(entity, lambda: True, lambda: seen.append('sent'), seen.append, '/up')
    assert seen == ['sent']
    assert not inflight.busy(entity)


def test_housekeeping_dispatches_fails_or_keeps_each_wait_for_a_server(inflight, clock):
    seen = []
    up = {}

    def is_ready(label):
        def check():
            if up.get(label) == 'broken':
                raise RuntimeError('graph gone')
            return up.get(label, False)
        return check

    def wait(label):
        inflight.wait_for_server(object(), is_ready(label), lambda: seen.append((label, 'sent')),
                                 lambda error: seen.append((label, str(error))), label)

    wait('/late')
    clock.now = READY_TIMEOUT_S
    for label in ('/ready', '/broken', '/waiting'):
        wait(label)
    up.update({'/ready': True, '/broken': 'broken'})
    inflight.housekeep()
    assert seen == [('/late', '/late not available (no server found)'), ('/ready', 'sent'),
                    ('/broken', 'graph gone')]
    seen.clear()
    up['/waiting'] = True
    inflight.housekeep()
    assert seen == [('/waiting', 'sent')]  # Kept until its server came up; sent only once.
    inflight.housekeep()
    assert seen == [('/waiting', 'sent')]


def test_a_parked_request_keeps_its_entity_busy_until_settled(inflight):
    entity = object()
    up = {'ready': False}
    inflight.wait_for_server(entity, lambda: up['ready'], lambda: None, lambda error: None, '/x')
    assert inflight.busy(entity)
    up['ready'] = True
    inflight.housekeep()
    assert not inflight.busy(entity)


def test_a_client_is_busy_until_its_response_lands(inflight):
    """An awaited response keeps its client out of cache eviction, then hands the future on."""
    client, future, handled = FakeClient(), FakeFuture(), []
    inflight.track_response(client, future, '/fake/set_parameters', handled.append)
    assert inflight.busy(client)
    future.fire()
    assert not inflight.busy(client)
    assert handled == [future]


def test_housekeeping_times_out_a_request_without_response(inflight, clock):
    failed, handled = [], []
    late_client, untracked_client, fine_client = FakeClient(), FakeClient(), FakeClient()
    late, untracked, fine = FakeFuture('late future'), FakeFuture('parameter future'), FakeFuture()
    inflight.track_response(late_client, late, '/slow', handled.append, failed.append)
    inflight.track_response(untracked_client, untracked, '/param', handled.append)  # No on_fail.
    clock.now = RESPONSE_TIMEOUT_S
    inflight.track_response(fine_client, fine, '/fine', handled.append, failed.append)
    inflight.housekeep()
    assert late_client.dropped == ['late future'] and untracked_client.dropped == ['parameter future']
    assert fine_client.dropped == []
    assert [str(error) for error in failed] == ['no response from /slow after 30 s']
    assert isinstance(failed[0], TimeoutError)
    assert not inflight.busy(late_client) and not inflight.busy(untracked_client)
    assert inflight.busy(fine_client)
    late.fire()  # A reply after the timeout is ignored.
    assert handled == []


def test_shutdown_fails_every_parked_request_and_awaited_response(inflight):
    failed = []
    tracked_client, untracked_client, parked = FakeClient(), FakeClient(), object()
    tracked, untracked = FakeFuture(), FakeFuture()
    inflight.wait_for_server(parked, lambda: False, lambda: failed.append('sent'),
                             lambda error: failed.append(('/parked', str(error))), '/parked')
    inflight.track_response(untracked_client, untracked, '/param', failed.append)  # No on_fail.
    inflight.track_response(tracked_client, tracked, '/call', failed.append,
                            lambda error: failed.append(('/call', str(error))))
    inflight.fail_all(RuntimeError('ROS bridge shut down'))
    assert failed == [('/parked', 'ROS bridge shut down'), ('/call', 'ROS bridge shut down')]
    assert not any(inflight.busy(entity) for entity in (parked, tracked_client, untracked_client))
    inflight.housekeep()  # Nothing is left to settle or time out.
    assert len(failed) == 2


def test_a_reply_that_lands_after_shutdown_is_ignored(inflight):
    """While the bridge waits for its goals at shutdown, a late reply must not run its handler:
    the handler would queue work on a bridge that has stopped."""
    handled = []
    tracked, untracked = FakeFuture(), FakeFuture()
    inflight.track_response(FakeClient(), tracked, '/call', handled.append, lambda error: None)
    inflight.track_response(FakeClient(), untracked, '/param', handled.append)
    inflight.fail_all(RuntimeError('ROS bridge shut down'))
    tracked.fire()
    untracked.fire()
    assert handled == []


def test_one_failing_callback_does_not_stop_the_others(inflight, clock):
    failed = []

    def broken(error):
        raise RuntimeError('caller gone')

    inflight.wait_for_server(object(), lambda: False, lambda: None, broken, '/a')
    inflight.wait_for_server(object(), lambda: False, lambda: None, failed.append, '/b')
    inflight.track_response(FakeClient(), FakeFuture(), '/c', lambda done: None, broken)
    inflight.track_response(FakeClient(), FakeFuture(), '/d', lambda done: None, failed.append)
    clock.now = RESPONSE_TIMEOUT_S
    inflight.housekeep()
    assert [str(error) for error in failed] == [
        '/b not available (no server found)', 'no response from /d after 30 s']
    failed.clear()
    inflight.wait_for_server(object(), lambda: False, lambda: None, broken, '/e')
    inflight.track_response(FakeClient(), FakeFuture(), '/f', lambda done: None, broken)
    inflight.track_response(FakeClient(), FakeFuture(), '/g', lambda done: None, failed.append)
    inflight.fail_all(RuntimeError('ROS bridge shut down'))
    assert [str(error) for error in failed] == ['ROS bridge shut down']


def test_a_goal_is_tracked_from_send_to_end(inflight):
    client, handle = ActionClient(), object()
    inflight.begin_goal('/fib', client, lambda event: None)
    assert inflight.busy(client)  # Sent, not yet accepted: the client must not be destroyed.
    assert inflight.goals()['/fib'].handle is None
    inflight.goal_accepted('/fib', handle)
    assert inflight.goals()['/fib'].handle is handle and inflight.busy(client)
    inflight.end_goal('/fib')
    assert inflight.goals() == {} and not inflight.busy(client)
    inflight.goal_accepted('/fib', handle)  # An acceptance for an ended goal changes nothing.
    inflight.end_goal('/fib')  # Ending twice is harmless.
    assert inflight.goals() == {}


def test_housekeeping_ends_a_goal_whose_server_vanished(inflight, clock):
    events = []
    clients = {name: ActionClient() for name in ('/gone', '/lost', '/back', '/unaccepted')}
    for name, client in clients.items():
        inflight.begin_goal(name, client, events.append)
        if name != '/unaccepted':
            inflight.goal_accepted(name, object())

    def tick(at, down):
        clock.now = at
        for name, client in clients.items():
            client.up = name not in down
        inflight.housekeep()

    tick(0.0, {'/gone', '/back', '/unaccepted'})
    tick(READY_TIMEOUT_S, {'/gone', '/lost', '/unaccepted'})
    assert sorted(inflight.goals()) == ['/back', '/lost', '/unaccepted']
    assert [(event.action_name, event.kind, event.payload) for event in events] == [
        ('/gone', ActionEventKind.ERROR, 'action server vanished while the goal was executing')]
    # /back's server came back, so its loss counts from scratch; /lost has been gone long enough.
    tick(2 * READY_TIMEOUT_S, {'/lost', '/back', '/unaccepted'})
    assert sorted(inflight.goals()) == ['/back', '/unaccepted']
    assert [event.action_name for event in events] == ['/gone', '/lost']
