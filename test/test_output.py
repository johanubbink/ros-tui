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

"""ros_output_to_log: C-level writes to fds 1 and 2 land in the log, the sys streams on the terminal."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SCRIPT = '''
import os, sys
from ros_tui.output import ros_output_to_log
with ros_output_to_log():
    os.write(1, b"rmw says hi on fd 1\\n")
    os.write(2, b"rmw says hi on fd 2\\n")
    print("ui on stderr", file=sys.__stderr__)
    print("ui on stdout", file=sys.__stdout__)
os.write(2, b"after, on fd 2\\n")
'''


def run(log_dir, script):
    env = {'ROS_LOG_DIR': str(log_dir), 'PATH': '/usr/bin:/bin'}
    return subprocess.run([sys.executable, '-c', script], cwd=REPO, env=env, capture_output=True, text=True)


def test_ros_output_goes_to_the_log_and_the_ui_to_the_terminal(tmp_path):
    out = run(tmp_path, SCRIPT)
    assert out.returncode == 0, out.stderr
    [log] = tmp_path.glob('ros_tui_*.log')
    assert log.read_text() == 'rmw says hi on fd 1\nrmw says hi on fd 2\n'
    assert out.stdout == 'ui on stdout\n'
    assert out.stderr == f'ui on stderr\nros_tui: ROS output was written to {log}\nafter, on fd 2\n'


def test_a_quiet_run_leaves_no_log(tmp_path):
    out = run(tmp_path, 'from ros_tui.output import ros_output_to_log\nwith ros_output_to_log(): pass\n')
    assert (out.returncode, out.stderr, list(tmp_path.iterdir())) == (0, '', [])


def test_a_crash_still_reaches_the_terminal(tmp_path):
    out = run(tmp_path, 'from ros_tui.output import ros_output_to_log\nwith ros_output_to_log(): 1 / 0\n')
    assert out.returncode == 1 and 'ZeroDivisionError' in out.stderr


def test_without_a_writable_log_dir_nothing_is_redirected(tmp_path):
    (tmp_path / 'file').write_text('')
    out = run(tmp_path / 'file' / 'log', SCRIPT)
    assert out.returncode == 0, out.stderr
    assert out.stdout == 'rmw says hi on fd 1\nui on stdout\n'
