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

"""Keep what ROS prints off the screen: file descriptors 1 and 2 go to a log file.

The RMW, DDS and rcutils write warnings straight to fd 1 and fd 2 from C. textual draws the UI on
``sys.__stderr__`` and sizes it from ``sys.__stdout__``, so both would collide. Inside
``ros_output_to_log()`` fds 1 and 2 point at a log file, while ``sys.__stdout__`` /
``sys.__stderr__`` (and ``sys.stdout`` / ``sys.stderr``) are copies of the original terminal.
"""

import contextlib
import os
import sys
import time
from pathlib import Path


def log_dir() -> Path:
    """Where ROS keeps its logs: $ROS_LOG_DIR, else $ROS_HOME/log, else ~/.ros/log."""
    if os.environ.get('ROS_LOG_DIR'):
        return Path(os.environ['ROS_LOG_DIR'])
    return Path(os.environ.get('ROS_HOME') or Path.home() / '.ros') / 'log'


@contextlib.contextmanager
def ros_output_to_log():
    """Send fds 1 and 2 to ``<log_dir>/ros_tui_<time>_<pid>.log`` for the block; yields its path.

    On the way out the fds and sys streams are restored before anything else prints, so a
    traceback still reaches the terminal. An empty log is removed; otherwise one line names it.
    If the log can't be created, nothing is redirected and the block gets None.
    """
    directory = log_dir()
    path = directory / f'ros_tui_{time.strftime("%Y-%m-%d-%H-%M-%S")}_{os.getpid()}.log'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        log_fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError:
        yield None
        return
    saved = {name: getattr(sys, name) for name in ('stdout', 'stderr', '__stdout__', '__stderr__')}
    for stream in (sys.stdout, sys.stderr):
        stream.flush()
    terminal_out, terminal_err = os.dup(1), os.dup(2)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)
    sys.stdout = sys.__stdout__ = os.fdopen(
        terminal_out, 'w', buffering=1, encoding=saved['stdout'].encoding, errors=saved['stdout'].errors)
    sys.stderr = sys.__stderr__ = os.fdopen(
        terminal_err, 'w', buffering=1, encoding=saved['stderr'].encoding, errors=saved['stderr'].errors)
    try:
        yield path
    finally:
        for stream in (sys.stdout, sys.stderr):
            stream.flush()
        os.dup2(terminal_out, 1)
        os.dup2(terminal_err, 2)
        sys.stdout.close()
        sys.stderr.close()
        for name, stream in saved.items():
            setattr(sys, name, stream)
        if path.stat().st_size:
            print(f'ros_tui: ROS output was written to {path}', file=sys.stderr)
        else:
            path.unlink()
