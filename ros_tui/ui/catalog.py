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

"""The catalogue: what there is to open, by kind, as the ☰ list and search show it. Pure Python."""

from dataclasses import dataclass
from typing import Any

KINDS = ('topics', 'services', 'actions', 'nodes')


@dataclass(frozen=True)
class CatalogItem:
    name: str
    type: str
    publishers: int = 0  # Topics only: decides whether a topic opens in Echo or Publish.
    subscribers: int = 0  # Topics only.


class Catalog:
    def __init__(self):
        self._by_kind: dict[str, list[CatalogItem]] = {kind: [] for kind in KINDS}
        self._items: dict[tuple[str, str], CatalogItem] = {}  # By (kind, name), for item().
        self._search: tuple[str, list] = ('', self.rows())  # The last search and its matches.

    def __getitem__(self, kind: str) -> list[CatalogItem]:
        return self._by_kind[kind]

    def __len__(self) -> int:
        return sum(len(items) for items in self._by_kind.values())

    def set(self, graph: Any) -> None:
        """Fill it from a GraphSnapshot (or anything with topics / services / actions / nodes of
        entries with a name and `types` or `type`; a topic's may count its publishers and subscribers)."""
        for kind in KINDS:
            self._by_kind[kind] = [
                CatalogItem(entry.name, _type_of(kind, entry),
                            getattr(entry, 'publishers', 0), getattr(entry, 'subscribers', 0))
                for entry in getattr(graph, kind, ())]
        self._items = {(kind, item.name): item for kind, item in self.rows()}
        self._search = ('', self.rows())

    def item(self, tab: Any) -> CatalogItem | None:
        """The item of `tab` (anything with a kind and a name), or None when the graph lost it."""
        return self._items.get((tab.kind, tab.name))

    def rows(self, chip: int = -1) -> list[tuple[str, CatalogItem]]:
        """The ☰ list: (kind, item), grouped by kind, only the kind KINDS[chip] unless chip is -1."""
        kinds = KINDS if chip < 0 else (KINDS[chip],)
        return [(kind, item) for kind in kinds for item in self._by_kind[kind]]

    def search(self, query: str) -> list[tuple[str, CatalogItem]]:
        """Search: (kind, item) whose name or type holds `query`, ignoring case. The last search is
        kept, as the search popup and the keys ask for the same one many times."""
        if self._search[0] != query:
            q = query.lower()
            self._search = (query, [(kind, item) for kind, item in self.rows()
                                    if q in item.name.lower() or q in item.type.lower()])
        return self._search[1]


def _type_of(kind: str, entry: Any) -> str:
    """The type shown and searched: a GraphSnapshot node's types[0] is its namespace ('namespace /')."""
    if hasattr(entry, 'type'):
        return entry.type
    types = getattr(entry, 'types', ())
    if kind == 'nodes':
        return f'namespace {types[0] if types else "/"}'
    return types[0] if types else ''
