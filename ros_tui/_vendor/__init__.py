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

"""ros_tui's own copy of textual and its dependencies (rich, pygments, ...).

The distro packages of textual are too old (or missing), so the pinned wheels listed in
vendor.lock are unpacked next to this file by scripts/vendor.py. Importing this package puts this
directory first on sys.path, so a plain ``import textual`` anywhere in ros_tui finds this copy.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
