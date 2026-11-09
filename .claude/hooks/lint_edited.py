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

"""Claude Code PostToolUse hook: lint a Python file Claude just edited.

flake8 with CI's settings (minus C901: complexity is gated by cognitive complexity instead), then
scripts/complexity.py on the file. Findings go back to Claude (exit 2). A non-Python file, a
vendored file, or a missing flake8 (and uv) is a silent no-op.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def flake8():
    if shutil.which('flake8'):
        return ['flake8']
    if shutil.which('uvx'):
        return ['uvx', '--quiet', 'flake8']
    return None


def findings(root, path):
    """The flake8 and complexity output for path, or '' when it is clean."""
    out = []
    lint = flake8()
    if lint:
        result = subprocess.run([*lint, '--max-line-length=127', '--extend-ignore=C901', path],
                                cwd=root, capture_output=True, text=True)
        out.append(result.stdout.strip())
    result = subprocess.run([sys.executable, 'scripts/complexity.py', path],
                            cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        out.append(result.stdout.strip() + '\n(split along a real seam; see docs/agentic-dev.md)')
    return '\n'.join(part for part in out if part)


def main():
    event = json.load(sys.stdin)
    root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or event.get('cwd') or '.').resolve()
    path = Path((event.get('tool_input') or {}).get('file_path', ''))
    if path.suffix != '.py' or not path.is_file():
        return 0
    try:
        relative = str(path.resolve().relative_to(root))
    except ValueError:
        return 0  # Outside this repo.
    if relative.startswith('ros_tui/_vendor/'):
        return 0
    found = findings(root, relative)
    if not found:
        return 0
    print(f'Lint findings in {relative} (fix them, or say why not):\n{found}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
