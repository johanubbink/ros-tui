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
CLIENT_CACHE_SIZE = 8
DEFAULT_QOS_DEPTH = 10

# Type introspection.
TYPE_CACHE_SIZE = 256
MAX_CONSTANTS_IN_COMMENT = 16

# Display truncation.
TRUNCATE_ARRAY_ELEMENTS = 16
TRUNCATE_STRING_CHARS = 256
TRUNCATE_RENDER_LINES = 60

# UI rendering.
ECHO_BUFFER_MAXLEN = 200
ECHO_HZ_WINDOW = 64
ECHO_RENDER_PERIOD_S = 0.1
ECHO_MAX_RENDER_PER_TICK = 3
FEEDBACK_BUFFER_MAXLEN = 200
FEEDBACK_MAX_RENDER_PER_TICK = 3
OUTPUT_LOG_MAX_LINES = 1000
FILTER_DEBOUNCE_S = 0.15
EDITOR_PARSE_DEBOUNCE_S = 0.3

# Topic publishing.
PUBLISH_RATE_MIN_HZ = 0.1
PUBLISH_RATE_MAX_HZ = 100.0
PUBLISH_DEFAULT_RATE_HZ = 10.0  # The repeat rate of a topic nobody publishes yet.

# Navigation model (ros_tui/ui/nav.py).
NAV_LOG_LINES = 8  # Key log lines kept (the design's "what the keys did" list).
NAV_ACTIVITY_MAX = 200  # Activity lines kept for :log.
