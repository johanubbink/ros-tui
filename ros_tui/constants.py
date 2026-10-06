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

"""Every tunable number of the TUI in one place. Nothing here is configurable at runtime."""

# ROS bridge thread.
GRAPH_POLL_PERIOD_S = 1.0
HOUSEKEEPING_PERIOD_S = 0.25
READY_TIMEOUT_S = 5.0  # Action-server discovery (5 sub-entities) can exceed 2 s under load.
RESPONSE_TIMEOUT_S = 30.0
SHUTDOWN_CANCEL_TIMEOUT_S = 1.0  # On quit, how long the bridge waits for servers to accept canceling running goals.
CLIENT_CACHE_SIZE = 8
DEFAULT_QOS_DEPTH = 10

# Type introspection.
TYPE_CACHE_SIZE = 256

# Display truncation.
TRUNCATE_ARRAY_ELEMENTS = 16
TRUNCATE_STRING_CHARS = 256

# Echo and feedback buffers.
ECHO_BUFFER_MAXLEN = 200
ECHO_HZ_WINDOW = 64
ECHO_DISPLAY_DIGITS = 6  # Significant digits of an echoed float on screen (the value keeps them all).
FEEDBACK_BUFFER_MAXLEN = 200

# Topic publishing.
PUBLISH_RATE_MIN_HZ = 0.1
PUBLISH_RATE_MAX_HZ = 100.0
PUBLISH_DEFAULT_RATE_HZ = 10.0  # The repeat rate of a topic nobody publishes yet.

# Navigation model (ros_tui/ui/nav.py).
NAV_LOG_LINES = 8  # Key log lines kept (the design's "what the keys did" list).
NAV_ACTIVITY_MAX = 200  # Activity lines kept for :log.
NAV_TOAST_S = 1.6  # How long a toast shows.
NAV_FLASH_S = 0.5  # How long the primary button flashes after a send (the design's flashT, 0.5 s).
NAV_ACTIVITY_FRESH_S = 1.6  # How long a new activity line stays highlighted (the design's .fl.new, 1.6 s).
NAV_ERRLINE_S = 6.0  # How long an errline shows under a panel (the design's inl, 6 s).
SEND_HISTORY_MAX = 20  # Sends kept per entry for [ and ] (the design's hist, 20).
SUMMARY_MAX_CHARS = 60  # A message summarised in an activity line ('a: 19, b: 23') is cut here.
ACTION_SPINNER_HZ = 4.0  # Frames per second of the ◐◓◑◒ spinner of an executing goal (the design's S.t*4).
UI_TICK_PERIOD_S = 0.1  # The UI's clock tick: drains the echoes and expires toasts.
