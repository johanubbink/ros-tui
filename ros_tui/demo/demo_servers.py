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

Brings up, on one node, something for each kind of entry:

- Actions  — ``example_interfaces/Fibonacci`` on ``/fibonacci`` (streams feedback,
  honours cancellation), so a goal can be sent and watched until SUCCEEDED or CANCELED.
- Services — ``example_interfaces/AddTwoInts`` on ``/add_two_ints``, and
  ``turtlesim/TeleportAbsolute`` on ``/set_pose`` (logs the pose it is asked for).
- Topics   — ``/chatter`` (``std_msgs/String`` @ ~1 Hz) for a calm echo, ``/counter``
  (``std_msgs/Int32`` @ ~50 Hz) to make the echo Hz/drop counters move, ``/localisation_pose``
  (``geometry_msgs/PoseWithCovarianceStamped`` @ ~2 Hz) as a richer, nested message type to
  browse and edit, ``/diagnostic_status`` (``diagnostic_msgs/DiagnosticStatus`` @ ~1 Hz, its
  ``level`` cycling through the OK/WARN/ERROR/STALE enum) as a target for the Enum helper,
  ``/inbox`` (``std_msgs/String`` subscriber) as a target for the Publish demo — what
  arrives is logged so you can see your published message land — and ``/goal_pose``
  (``geometry_msgs/PoseStamped`` subscriber), a Header + Quaternion target for the field helpers.
- Parameters — ``publish_rate`` (double) and ``frame_id`` (string), only there to edit and set
  from the node entry: nothing reads them.

This mirrors the in-process ``FixtureServers`` used by the test suite
(``test/conftest.py``), but as an installable node with public-looking names. The test harness's
``DEMO_GRAPH`` (``test/harness/fake_bridge.py``) shows the same world.
"""

import math
import time

import rclpy
from diagnostic_msgs.msg import DiagnosticStatus
from example_interfaces.action import Fibonacci
from example_interfaces.srv import AddTwoInts
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Int32, String
from turtlesim.srv import TeleportAbsolute

FIBONACCI_ACTION = '/fibonacci'
ADD_TWO_INTS_SERVICE = '/add_two_ints'
SET_POSE_SERVICE = '/set_pose'
CHATTER_TOPIC = '/chatter'
COUNTER_TOPIC = '/counter'
LOCALISATION_POSE_TOPIC = '/localisation_pose'
DIAGNOSTIC_STATUS_TOPIC = '/diagnostic_status'
INBOX_TOPIC = '/inbox'
GOAL_POSE_TOPIC = '/goal_pose'

CHATTER_PERIOD_S = 1.0
COUNTER_PERIOD_S = 0.02  # ~50 Hz, fast enough to exercise the echo Hz/drop counters.
LOCALISATION_POSE_PERIOD_S = 0.5  # ~2 Hz, a nested message type to browse and edit.
DIAGNOSTIC_STATUS_PERIOD_S = 1.0  # ~1 Hz; cycles the `level` enum for the Enum helper.
FIBONACCI_FEEDBACK_PERIOD_S = 0.3  # Slow enough to watch the feedback stream in the UI.

# (level constant, label) cycled by the /diagnostic_status publisher. `level` is an octet enum
# field; its constants (OK/WARN/ERROR/STALE) are what the Enum helper offers.
DIAGNOSTIC_LEVELS = (
    (DiagnosticStatus.OK, 'OK'),
    (DiagnosticStatus.WARN, 'WARN'),
    (DiagnosticStatus.ERROR, 'ERROR'),
    (DiagnosticStatus.STALE, 'STALE'),
)


class DemoServers(Node):
    """One node hosting a Fibonacci action, AddTwoInts service and a few topics."""

    def __init__(self):
        super().__init__('ros_tui_demo_servers')
        # Parameters to change and set from the node entry. Nothing reads them.
        self.declare_parameter('publish_rate', 10.0)
        self.declare_parameter('frame_id', 'map')
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
        self._set_pose_service = self.create_service(
            TeleportAbsolute, SET_POSE_SERVICE, self._set_pose, callback_group=callback_group
        )

        self._chatter_publisher = self.create_publisher(String, CHATTER_TOPIC, 10)
        self._chatter_count = 0
        self.create_timer(CHATTER_PERIOD_S, self._publish_chatter, callback_group=callback_group)

        self._counter_publisher = self.create_publisher(Int32, COUNTER_TOPIC, 10)
        self._counter = 0
        self.create_timer(COUNTER_PERIOD_S, self._publish_counter, callback_group=callback_group)

        self._localisation_pose_publisher = self.create_publisher(
            PoseWithCovarianceStamped, LOCALISATION_POSE_TOPIC, 10
        )
        self._localisation_step = 0
        self.create_timer(
            LOCALISATION_POSE_PERIOD_S, self._publish_localisation_pose, callback_group=callback_group
        )

        self._diagnostic_publisher = self.create_publisher(
            DiagnosticStatus, DIAGNOSTIC_STATUS_TOPIC, 10
        )
        self._diagnostic_step = 0
        self.create_timer(
            DIAGNOSTIC_STATUS_PERIOD_S, self._publish_diagnostic_status, callback_group=callback_group
        )

        self.create_subscription(
            String, INBOX_TOPIC, self._on_inbox, 10, callback_group=callback_group
        )
        self.create_subscription(
            PoseStamped, GOAL_POSE_TOPIC, self._on_goal_pose, 10, callback_group=callback_group
        )

        self.get_logger().info(
            'Demo servers ready: action %s, services %s, %s, topics %s, %s, %s, %s, subs %s, %s'
            % (
                FIBONACCI_ACTION,
                ADD_TWO_INTS_SERVICE,
                SET_POSE_SERVICE,
                CHATTER_TOPIC,
                COUNTER_TOPIC,
                LOCALISATION_POSE_TOPIC,
                DIAGNOSTIC_STATUS_TOPIC,
                INBOX_TOPIC,
                GOAL_POSE_TOPIC,
            )
        )

    def _publish_chatter(self):
        self._chatter_count += 1
        self._chatter_publisher.publish(String(data=f'chatter {self._chatter_count}'))

    def _publish_counter(self):
        self._counter += 1
        self._counter_publisher.publish(Int32(data=self._counter))

    def _publish_localisation_pose(self):
        self._localisation_step += 1
        angle = self._localisation_step * LOCALISATION_POSE_PERIOD_S  # radians, ~1 rad/s.
        message = PoseWithCovarianceStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = 'map'
        pose = message.pose.pose
        pose.position.x = 2.0 * math.cos(angle)
        pose.position.y = 2.0 * math.sin(angle)
        pose.orientation.z = math.sin(angle / 2.0)
        pose.orientation.w = math.cos(angle / 2.0)
        # 6x6 row-major covariance; small variance on x/y/yaw, the rest left at zero.
        message.pose.covariance[0] = 0.05  # x
        message.pose.covariance[7] = 0.05  # y
        message.pose.covariance[35] = 0.02  # yaw
        self._localisation_pose_publisher.publish(message)

    def _publish_diagnostic_status(self):
        level, label = DIAGNOSTIC_LEVELS[self._diagnostic_step % len(DIAGNOSTIC_LEVELS)]
        self._diagnostic_step += 1
        self._diagnostic_publisher.publish(
            DiagnosticStatus(
                level=level, name='demo_check', message=f'cycling level: {label}',
                hardware_id='demo-0',
            )
        )

    def _on_inbox(self, message):
        self.get_logger().info(f'/inbox received: {message.data!r}')

    def _on_goal_pose(self, message):
        position, orientation = message.pose.position, message.pose.orientation
        self.get_logger().info(
            f'/goal_pose received in {message.header.frame_id!r}: '
            f'position ({position.x}, {position.y}, {position.z}), '
            f'orientation ({orientation.x}, {orientation.y}, {orientation.z}, {orientation.w})'
        )

    def _set_pose(self, request, response):
        self.get_logger().info(f'/set_pose: x={request.x} y={request.y} theta={request.theta}')
        return response

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
