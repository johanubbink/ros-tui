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

"""The `:` command line: what is typed, the suggestions under it and which one is picked.

Pure Python. It only edits the line and says which command enter runs (`picked`); NavState runs it
from its own table of commands.
"""

from dataclasses import dataclass

# The `:` commands and their suggestion text. A trailing space means it takes an argument.
COMMANDS = (
    ('log', 'show all activity'),
    ('topics', 'list only topics'),
    ('services', 'list only services'),
    ('actions', 'list only actions'),
    ('nodes', 'list only nodes'),
    ('all', 'list everything'),
    ('rate ', 'set the repeat rate, e.g. :rate 5'),
    ('echo', 'switch this topic to Echo'),
    ('pub', 'switch this topic to Publish'),
    ('close', 'close this tab'),
    ('help', 'show the keys'),
    ('q', 'quit'),
)
MAX_SUGGESTIONS = 7


@dataclass
class CommandLine:
    q: str = ''
    cur: int = 0
    moved: bool = False  # ↑↓ picked a suggestion, so enter runs it rather than the typed text.

    def suggestions(self) -> list[tuple[str, str]]:
        """The commands to suggest: prefix matches, or the one command once an argument is typed."""
        q = self.q.lstrip()
        word = q.split(' ')[0]
        return [c for c in COMMANDS if not q or (c[0].strip() == word if ' ' in q else c[0].startswith(word))
                ][:MAX_SUGGESTIONS]

    def _clamped(self) -> list[tuple[str, str]]:
        suggestions = self.suggestions()
        self.cur = min(self.cur, max(0, len(suggestions) - 1))
        return suggestions

    def edit(self, text: str) -> None:
        self.q = text
        self.cur = 0
        self.moved = False

    def complete(self) -> None:
        suggestions = self._clamped()
        if ' ' not in self.q and suggestions:
            self.edit(suggestions[self.cur][0])

    def move(self, delta: int) -> None:
        suggestions = self._clamped()
        if suggestions:
            self.cur = (self.cur + delta) % len(suggestions)
            self.moved = True

    def picked(self) -> str:
        """What enter runs: the typed command, or the picked suggestion for a partial word ('se' runs
        services) or picked with ↑↓. One that ends in a space still wants its argument."""
        suggestions = self._clamped()
        q = self.q
        word = q.strip().split(' ')[0]
        partial = q.strip() and not any(c[0].strip() == word for c in COMMANDS)
        if suggestions and ' ' not in q and (self.moved or partial):
            q = suggestions[self.cur][0]
        return q
