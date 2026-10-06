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

"""Shared test fixtures: isolated ROS domain, in-process peer servers, real bridge."""

import itertools
import os
import threading
import time

import pytest
import rclpy
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from ros_tui.ros.bridge import RosBridge
from std_msgs.msg import String

FIBONACCI_ACTION = '/tui_test_fibonacci'
ADD_TWO_INTS_SERVICE = '/tui_test_add_two_ints'
CHATTER_TOPIC = '/tui_test_chatter'
INBOX_TOPIC = '/tui_test_inbox'
FIBONACCI_FEEDBACK_PERIOD_S = 0.05


def wait_for(predicate, timeout=5.0, period=0.02):
    """Poll ``predicate`` until truthy or the timeout elapses; returns its last value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(period)
    return predicate()


@pytest.fixture(scope='session')
def ros_domain():
    import domain_coordinator

    with domain_coordinator.domain_id() as domain:
        os.environ['ROS_DOMAIN_ID'] = str(domain)
        yield domain


class FixtureServers:
    """One node with a Fibonacci action, AddTwoInts service, 100 Hz chatter, inbox sub."""

    def __init__(self, context):
        self.node = rclpy.create_node('tui_test_fixtures', context=context)
        # A declared parameter the bridge param tests can list and set without touching
        # use_sim_time (which would freeze this node's timers and break sibling tests).
        self.node.declare_parameter('test_param', 0)
        self.inbox_messages: list[str] = []
        self.canceled_goals = 0  # Goals the Fibonacci server ended as canceled.
        callback_group = ReentrantCallbackGroup()
        self.action_server = ActionServer(
            self.node,
            Fibonacci,
            FIBONACCI_ACTION,
            execute_callback=self._execute_fibonacci,
            cancel_callback=lambda request: CancelResponse.ACCEPT,
            callback_group=callback_group,
        )
        self.service = self.node.create_service(
            AddTwoInts, ADD_TWO_INTS_SERVICE, self._add_two_ints, callback_group=callback_group
        )
        self.chatter_publisher = self.node.create_publisher(String, CHATTER_TOPIC, 10)
        self.chatter_count = 0
        self.node.create_timer(0.01, self._publish_chatter, callback_group=callback_group)
        self.node.create_subscription(
            String,
            INBOX_TOPIC,
            lambda message: self.inbox_messages.append(message.data),
            10,
            callback_group=callback_group,
        )

    def _publish_chatter(self):
        self.chatter_count += 1
        self.chatter_publisher.publish(String(data=f'chatter {self.chatter_count}'))

    def _add_two_ints(self, request, response):
        response.sum = request.a + request.b
        return response

    def _execute_fibonacci(self, goal_handle):
        sequence = [0, 1]
        for index in range(1, goal_handle.request.order):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                self.canceled_goals += 1
                return Fibonacci.Result(sequence=sequence)
            sequence.append(sequence[index] + sequence[index - 1])
            goal_handle.publish_feedback(Fibonacci.Feedback(sequence=sequence))
            time.sleep(FIBONACCI_FEEDBACK_PERIOD_S)
        goal_handle.succeed()
        return Fibonacci.Result(sequence=sequence)


@pytest.fixture(scope='module')
def fixture_servers(ros_domain):
    context = rclpy.Context()
    rclpy.init(context=context)
    servers = FixtureServers(context)
    executor = MultiThreadedExecutor(num_threads=4, context=context)
    executor.add_node(servers.node)
    spin_thread = threading.Thread(target=executor.spin, name='fixture-spin', daemon=True)
    spin_thread.start()
    yield servers
    executor.shutdown()
    spin_thread.join(timeout=3.0)
    servers.node.destroy_node()
    rclpy.shutdown(context=context)


_bridge_counter = itertools.count()


@pytest.fixture
def bridge(ros_domain):
    # Unique node name per test: rapid create/destroy of same-named nodes confuses
    # DDS discovery and made action servers intermittently unreachable.
    ros_bridge = RosBridge(node_name=f'ros_tui_under_test_{next(_bridge_counter)}')
    ros_bridge.start()
    yield ros_bridge
    ros_bridge.shutdown()
