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

"""A self-contained set of example servers to exercise and showcase ros_tui.

Brings up, on one node, one entity for each tab:

- Actions  — ``example_interfaces/Fibonacci`` on ``/fibonacci`` (streams feedback,
  honours cancellation), so the Actions tab can send a goal and watch SENDING →
  EXECUTING → SUCCEEDED/CANCELED.
- Services — ``example_interfaces/AddTwoInts`` on ``/add_two_ints``.
- Topics   — ``/chatter`` (``std_msgs/String`` @ ~1 Hz) for a calm echo, ``/counter``
  (``std_msgs/Int32`` @ ~50 Hz) to make the echo Hz/drop counters move, and ``/inbox``
  (``std_msgs/String`` subscriber) as a target for the Publish demo — what arrives is
  logged so you can see your published message land.

This mirrors the in-process ``FixtureServers`` used by the test suite
(``test/conftest.py``), but as an installable node with public-looking names.
"""

import time

import rclpy
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Int32, String

FIBONACCI_ACTION = '/fibonacci'
ADD_TWO_INTS_SERVICE = '/add_two_ints'
CHATTER_TOPIC = '/chatter'
COUNTER_TOPIC = '/counter'
INBOX_TOPIC = '/inbox'

CHATTER_PERIOD_S = 1.0
COUNTER_PERIOD_S = 0.02  # ~50 Hz, fast enough to exercise the echo Hz/drop counters.
FIBONACCI_FEEDBACK_PERIOD_S = 0.3  # Slow enough to watch the feedback stream in the UI.


class DemoServers(Node):
    """One node hosting a Fibonacci action, AddTwoInts service and a few topics."""

    def __init__(self):
        super().__init__('ros_tui_demo_servers')
        callback_group = ReentrantCallbackGroup()

        self._action_server = ActionServer(
            self,
            Fibonacci,
            FIBONACCI_ACTION,
            execute_callback=self._execute_fibonacci,
            cancel_callback=lambda request: CancelResponse.ACCEPT,
            callback_group=callback_group,
        )
        self._service = self.create_service(
            AddTwoInts, ADD_TWO_INTS_SERVICE, self._add_two_ints, callback_group=callback_group
        )

        self._chatter_publisher = self.create_publisher(String, CHATTER_TOPIC, 10)
        self._chatter_count = 0
        self.create_timer(CHATTER_PERIOD_S, self._publish_chatter, callback_group=callback_group)

        self._counter_publisher = self.create_publisher(Int32, COUNTER_TOPIC, 10)
        self._counter = 0
        self.create_timer(COUNTER_PERIOD_S, self._publish_counter, callback_group=callback_group)

        self.create_subscription(
            String, INBOX_TOPIC, self._on_inbox, 10, callback_group=callback_group
        )

        self.get_logger().info(
            'Demo servers ready: action %s, service %s, topics %s, %s, sub %s'
            % (FIBONACCI_ACTION, ADD_TWO_INTS_SERVICE, CHATTER_TOPIC, COUNTER_TOPIC, INBOX_TOPIC)
        )

    def _publish_chatter(self):
        self._chatter_count += 1
        self._chatter_publisher.publish(String(data=f'chatter {self._chatter_count}'))

    def _publish_counter(self):
        self._counter += 1
        self._counter_publisher.publish(Int32(data=self._counter))

    def _on_inbox(self, message):
        self.get_logger().info(f'/inbox received: {message.data!r}')

    def _add_two_ints(self, request, response):
        response.sum = request.a + request.b
        self.get_logger().info(f'/add_two_ints: {request.a} + {request.b} = {response.sum}')
        return response

    def _execute_fibonacci(self, goal_handle):
        order = goal_handle.request.order
        self.get_logger().info(f'/fibonacci: computing order {order}')
        sequence = [0, 1]
        for index in range(1, order):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                self.get_logger().info('/fibonacci: canceled')
                return Fibonacci.Result(sequence=sequence)
            sequence.append(sequence[index] + sequence[index - 1])
            goal_handle.publish_feedback(Fibonacci.Feedback(sequence=sequence))
            time.sleep(FIBONACCI_FEEDBACK_PERIOD_S)
        goal_handle.succeed()
        return Fibonacci.Result(sequence=sequence)


def main(args=None):
    rclpy.init(args=args)
    node = DemoServers()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
