#!/usr/bin/env python3
# Copyright 2026 Jonas Vervoort
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

"""Pure text helpers behind the field wizards — no textual dependency.

These locate the field under the editor's cursor, find its YAML block, and render a wizard's
result back into that block. They carry no textual/rclpy import so they're unit-tested
standalone (``test/test_field_wizards.py``).
"""

from typing import Any

from ros_tui.ros.message_yaml import _dump_yaml


def cursor_field_path(text: str, row: int) -> list[str]:
    """Dotted key path (as a list) of the YAML field enclosing ``row``.

    An indentation-stack walk: each mapping key opens a level; a line at the same or lower
    indent closes its siblings/ancestors first. List items and comments carry no key.
    """
    lines = text.splitlines()
    if not lines:
        return []
    row = max(0, min(row, len(lines) - 1))
    stack: list[tuple[int, str]] = []  # (indent, key)
    for line in lines[: row + 1]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('- '):
            continue
        separator = line.find(':')
        if separator == -1:
            continue
        key = line[:separator].strip()
        if not key:
            continue
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
    return [key for _, key in stack]


def field_node_at(structure: Any, path: list[str]) -> Any:
    """The ``FieldNode`` at ``path`` in a ``FieldNode`` tuple, or None if absent."""
    nodes = structure
    node = None
    for name in path:
        node = next((candidate for candidate in nodes if candidate.name == name), None)
        if node is None:
            return None
        nodes = node.children
    return node


def field_type_at(structure: Any, path: list[str]) -> str | None:
    """Type label of the field at ``path`` in a ``FieldNode`` tuple, or None if absent."""
    node = field_node_at(structure, path)
    return node.type_label if node is not None else None


def field_block_range(text: str, path: list[str]) -> tuple[int, int, int] | None:
    """Line span ``(start, end_exclusive, indent)`` of the field block at ``path``.

    The block runs from the field's ``key:`` line to the next line at the same or lower
    indent (a sibling/ancestor), stopping before a trailing comment block (e.g. the
    ``# constants:`` hint) or EOF. Trailing blank lines are excluded.
    """
    lines = text.splitlines()
    start = next((i for i in range(len(lines)) if cursor_field_path(text, i) == path), None)
    if start is None:
        return None
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        stripped = lines[end].strip()
        if not stripped:
            end += 1
            continue
        if stripped.startswith('#'):
            break
        if len(lines[end]) - len(lines[end].lstrip()) <= indent:
            break
        end += 1
    while end - 1 > start and not lines[end - 1].strip():
        end -= 1  # Don't swallow blank lines that separate the block from what follows.
    return start, end, indent


def render_field_block(field_name: str, value: Any, indent: int) -> str:
    """Render ``{field_name: value}`` as YAML, each line indented by ``indent`` spaces."""
    pad = ' ' * indent
    dumped = _dump_yaml({field_name: value}).rstrip('\n')
    return '\n'.join(pad + line if line else line for line in dumped.splitlines())


def replace_block(text: str, start: int, end_exclusive: int, new_block: str) -> tuple[str, int]:
    """Replace lines ``[start, end_exclusive)`` with ``new_block``; return (text, cursor_row)."""
    lines = text.splitlines()
    result = lines[:start] + new_block.splitlines() + lines[end_exclusive:]
    joined = '\n'.join(result)
    if text.endswith('\n'):
        joined += '\n'
    return joined, start
