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

"""The field rows of a message: one row per field, nested messages and lists folding in place.

Pure Python (no textual, no rclpy). `FieldRows` works on a message's static structure (the
`FieldNode`s of `message_yaml.message_structure`, or anything with `name`, `type_label`, `children`
and `constants`) and its value as plain data (`message_yaml.message_to_plain`). Every row has a
`shape`:

- LEAF: a number, bool or string. Shown and typed as its value.
- COMPACT: a small message on one row as flow YAML, `{x: 1.0, y: 2.0, z: 0.0}` (COMPACT_TYPES).
  `header: auto` and `stamp: now` pass through as message_yaml's stamp-at-send magic.
- MESSAGE: any other nested message, `▸ pose {…}`. Unfolding it lists its fields one level deeper.
  It starts unfolded when it is the only field, or when all its fields are compact (a Pose).
- ARRAY: a list or fixed array, `▸ points [3 items]`. Unfolding it lists `[0]`, `[1]` …; elements
  are added and deleted in place. A list of numbers or strings can also be typed whole, `[1, 2]`.

Typed text is parsed per row (`parse`): a string field takes bare text as the string, an enum
field (a whole number with constants) a constant's name or the start of one ('err' is ERROR), the
other fields read it as YAML and check its type, with a message that names the field and quotes the
text ("a needs a whole number, got "x""). Ranges, sizes and keys are checked by the message's own
validator (`build_message`, passed in as `validate`): its `FieldError.path` is mapped back to a row
(`reveal`), so validation stays in one place.
"""

import copy
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

import yaml

from ros_tui.constants import ECHO_DISPLAY_DIGITS, HEADER_AUTO, TIME_NOW

# Messages small enough to be typed on one row as flow YAML. Keep this set small.
COMPACT_TYPES = frozenset({
    'geometry_msgs/Point', 'geometry_msgs/Point32', 'geometry_msgs/Vector3', 'geometry_msgs/Quaternion',
    'geometry_msgs/Pose2D', 'std_msgs/Header', 'builtin_interfaces/Time', 'builtin_interfaces/Duration',
})
# Compact types with a stamp-at-send word (message_yaml.build_message's magic values).
MAGIC_WORDS = {'std_msgs/Header': HEADER_AUTO, 'builtin_interfaces/Time': TIME_NOW}

LEAF, COMPACT, MESSAGE, ARRAY = 'leaf', 'compact', 'message', 'array'

FLOAT_TYPES = frozenset({'float', 'double', 'float32', 'float64'})
BOOL_TYPE = 'boolean'

Path = tuple[str | int, ...]

_FIXED = re.compile(r'^(?P<element>.+)\[(?P<size>\d+)\]$')
_SEQUENCE = re.compile(r'^sequence<(?P<element>.+?)(?:, ?(?P<bound>\d+))?>$')
_PATH_PART = re.compile(r'([^.\[\]]+)|\[(\d+)\]')
_FIELD_PREFIX = re.compile(r"^(?:The '[^']*' field |byte field )")


class ArrayInfo(NamedTuple):
    element: str  # The element's type label.
    size: int | None  # The size of a fixed array (T[N]), else None.
    bound: int | None  # The most elements a bounded sequence (sequence<T, N>) holds, else None.


class Element(NamedTuple):
    """The type of one element of an ARRAY row, shaped like a FieldNode."""

    name: str
    type_label: str
    children: tuple = ()
    constants: tuple = ()


def array_info(label: str) -> ArrayInfo | None:
    match = _SEQUENCE.match(label)
    if match:
        return ArrayInfo(match['element'], None, int(match['bound']) if match['bound'] else None)
    match = _FIXED.match(label)
    return ArrayInfo(match['element'], int(match['size']), None) if match else None


def element_of(node: Any) -> Element:
    return Element(node.name, array_info(node.type_label).element, node.children, node.constants)


def shape_of(node: Any) -> str:
    label = node.type_label
    if array_info(label):
        return ARRAY
    if label in COMPACT_TYPES:
        return COMPACT
    return MESSAGE if '/' in label else LEAF


def short_type(label: str) -> str:
    """The type as a row's hint shows it: 'int64', 'Point', 'double[9]', 'Point32[]', 'double[<=3]'."""
    info = array_info(label)
    if info:
        size = info.size if info.size is not None else f'<={info.bound}' if info.bound else ''
        return f'{short_type(info.element)}[{size}]'
    return label.rsplit('/', 1)[-1]


def is_string(label: str) -> bool:
    return label.startswith(('string', 'wstring'))


def default_value(node: Any) -> Any:
    """A zero value for `node` (a new list element): 0, 0.0, false, '', [] or a dict of zeros."""
    label = node.type_label
    info = array_info(label)
    if info:
        return [default_value(element_of(node)) for _ in range(info.size or 0)]
    if node.children or '/' in label:
        return {child.name: default_value(child) for child in node.children}
    if label == BOOL_TYPE:
        return False
    if label in FLOAT_TYPES:
        return 0.0
    return '' if is_string(label) else 0


def path_text(path: Path) -> str:
    """A path as the user reads it and FieldError reports it: 'pose.position', 'points[1].x'."""
    text = ''
    for part in path:
        text += f'[{part}]' if isinstance(part, int) else (f'.{part}' if text else part)
    return text


def parse_path(text: str) -> Path:
    return tuple(int(index) if index else name for name, index in _PATH_PART.findall(text))


def _scalar_yaml(value: Any) -> str | None:
    """A bool, int or float as yaml.safe_dump writes it (without the cost of a dump), else None."""
    kind = type(value)
    if kind is bool:
        return 'true' if value else 'false'
    if kind is int:
        return str(value)
    if kind is not float:
        return None
    if value != value:
        return '.nan'
    if value in (math.inf, -math.inf):
        return '.inf' if value > 0 else '-.inf'
    text = repr(value).lower()
    return text.replace('e', '.0e', 1) if '.' not in text and 'e' in text else text


def flow_yaml(value: Any) -> str:
    """`value` as one line of YAML that parses back to it: '5.0', '[1, 2]', "{x: 1.0, y: 'a b'}"."""
    text = _scalar_yaml(value)
    if text is not None:
        return text
    if type(value) is list:  # A list of numbers (and bools) is the common non-scalar: no dump either.
        items = [_scalar_yaml(item) for item in value]
        if None not in items:
            return f'[{", ".join(items)}]'
    text = yaml.safe_dump(value, default_flow_style=True, sort_keys=False, width=math.inf, allow_unicode=True).strip()
    if text.endswith('\n...'):  # safe_dump ends a bare scalar with a document-end marker.
        text = text[:-len('\n...')].rstrip()
    return text


def summary(values: dict, limit: int) -> str:
    """The top-level fields as one line for the activity strip: 'a: 19, b: 23' (cut at `limit`)."""
    text = ', '.join(f'{name}: {flow_yaml(value)}' for name, value in values.items())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def describe(error: Any, typed: str = '') -> str:
    """A validator's FieldError as the user reads it: the field first, then what is wrong."""
    detail = _FIELD_PREFIX.sub('', str(getattr(error, 'detail', error)))
    path = getattr(error, 'path', '')
    if not detail.startswith('must'):
        return f'{path}: {detail}' if path else detail
    if typed and 'got' not in detail:
        detail += f', got "{typed}"'
    return f'{path} {detail}'


def within(path: str, field: str) -> bool:
    """True when the field path `path` is `field` or inside it."""
    return path == field or path.startswith((field + '.', field + '['))


@dataclass(frozen=True)
class Row:
    path: Path
    node: Any  # FieldNode-like: name, type_label, children, constants.
    depth: int
    shape: str
    value: Any
    open: bool = False  # An unfolded MESSAGE or ARRAY.

    @property
    def field(self) -> str:
        return path_text(self.path)

    @property
    def key(self) -> str:
        last = self.path[-1]
        return f'[{last}]' if isinstance(last, int) else last

    @property
    def label(self) -> str:
        return self.node.type_label

    @property
    def hint(self) -> str:
        return short_type(self.label)

    @property
    def folds(self) -> bool:
        return self.shape in (MESSAGE, ARRAY)

    @property
    def editable(self) -> bool:
        if self.shape == ARRAY:
            return shape_of(element_of(self.node)) == LEAF
        return self.shape in (LEAF, COMPACT)

    @property
    def fresh(self) -> bool:
        """The first typed key replaces the value: a bool, or a number that is still 0."""
        return self.label == BOOL_TYPE or (self.style == 'num' and self.value == 0)

    @property
    def style(self) -> str:
        """How the value is coloured: 'num', 'str' or ''."""
        if self.shape != LEAF:
            return ''
        return 'str' if is_string(self.label) else 'num'

    @property
    def text(self) -> str:
        """The value as the row shows it."""
        if self.shape == MESSAGE:
            return '' if self.open else ('{…}' if self.node.children else '{}')
        if self.shape == ARRAY:
            count = len(self.value or ())
            return f'[{count} item{"" if count == 1 else "s"}]'
        if self.shape == LEAF and is_string(self.label):
            return "'" + str(self.value).replace("'", "''") + "'"
        return flow_yaml(self.value)

    @property
    def enum_name(self) -> str:
        """The name of the enum constant the value is ('WARN' for level 1), or ''."""
        return next((name for name, number in self.node.constants or () if number == self.value), '')

    def edit_text(self) -> str:
        """The text an edit starts from; parse() reads it back to the same value."""
        if self.shape == LEAF and is_string(self.label):
            text = str(self.value)
            return text if _parse_string(text) == text else flow_yaml(text)
        return flow_yaml(self.value)


def _parse_string(text: str) -> str:
    """Bare text is the string itself; text in quotes is read as a YAML string ('' is empty)."""
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in '\'"':
        try:
            value = yaml.safe_load(stripped)
        except yaml.YAMLError:
            return text
        return value if isinstance(value, str) else text
    return text


def _load(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def parse_list(field: str, text: str) -> list:
    """`text` read as a YAML list (its elements unchecked), or ValueError naming the field. A node's
    array parameters are read by it too (entries/node.parse_value)."""
    value = _load(text.strip())
    if not isinstance(value, list):
        raise ValueError(f'{field} needs a list like [1, 2], got "{text.strip()}"')
    return value


def parse_scalar(label: str, field: str, text: str) -> Any:
    """`text` read as a value of the primitive type `label`, or ValueError naming the field. Node
    parameters are read by it too (entries/node.parse_value)."""
    shown = text.strip()
    if is_string(label):
        return _parse_string(text)
    if label == BOOL_TYPE:
        if shown.lower() in ('true', 'false'):
            return shown.lower() == 'true'
        raise ValueError(f'{field} needs true or false, got "{shown}"')
    if label in FLOAT_TYPES:
        try:
            return float(shown)  # Also 1e-3, nan and inf.
        except ValueError:
            raise ValueError(f'{field} needs a number, got "{shown}"') from None
    number = _whole_number(shown)
    if number is None:
        raise ValueError(f'{field} needs a whole number, got "{shown}"')
    return number


def enum_value(constants: tuple, field: str, text: str) -> int:
    """`text` typed into an enum field: a constant's name or the start of one, in any case ('err'
    is ERROR), or a number. ValueError naming the field and its names otherwise."""
    typed = text.strip()
    lowered = typed.lower()
    match = (next((number for name, number in constants if name.lower() == lowered), None)
             if lowered else None)
    if match is None and lowered:
        match = next((number for name, number in constants if name.lower().startswith(lowered)), None)
    if match is not None:
        return match
    number = _whole_number(typed)
    if number is None:
        names = ' / '.join(name for name, _ in constants)
        raise ValueError(f'{field} needs {names} or a number, got "{typed}"')
    return number


def enum_matches(constants: tuple, text: str) -> str:
    """The completion next to an enum field being typed: the constants that `text` could mean,
    'OK=0  WARN=1  ERROR=2  STALE=3 · type a name or number'."""
    typed = text.strip().lower()
    matches = [f'{name}={number}' for name, number in constants
               if not typed or name.lower().startswith(typed) or str(number) == typed]
    return ('  '.join(matches) if matches else 'no match') + ' · type a name or number'


def _whole_number(text: str) -> int | None:
    """Decimal, so a typed 019 is 19 (YAML would read 017 as octal); 5.0 is whole too."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def coerce(node: Any, value: Any) -> Any:
    """`value` with whole numbers in float fields made floats, so it shows as it will be sent."""
    label = node.type_label
    if array_info(label):
        element = element_of(node)
        return [coerce(element, item) for item in value] if isinstance(value, list) else value
    if isinstance(value, dict):
        children = {child.name: child for child in node.children}
        return {key: coerce(children[key], item) if key in children else item for key, item in value.items()}
    if label in FLOAT_TYPES and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def _merge(old: Any, new: Any) -> Any:
    """A typed flow map on top of the old value: {x: 1} keeps the old y and z."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return new
    return {**old, **{key: _merge(old.get(key), value) for key, value in new.items()}}


def _template(node: Any) -> str:
    return '{' + ', '.join(f'{child.name}: …' for child in node.children) + '}'


def parse(row: Row, text: str) -> Any:
    """The value typed for `row`. Raises ValueError with the message the user sees."""
    field, label, shown = row.field, row.label, text.strip()
    if row.shape == COMPACT:
        magic = MAGIC_WORDS.get(label)
        if magic and shown == magic:
            return magic
        value = _load(shown)
        if not isinstance(value, dict):
            needs = f'{magic} or {_template(row.node)}' if magic else _template(row.node)
            raise ValueError(f'{field} needs {needs}, got "{shown}"')
        return coerce(row.node, _merge(row.value, value))
    if row.shape == ARRAY:
        element = array_info(label).element
        return [parse_scalar(element, f'{field}[{index}]', flow_yaml(item) if not isinstance(item, str) else item)
                for index, item in enumerate(parse_list(field, shown))]
    if row.node.constants:
        return enum_value(row.node.constants, field, text)
    return parse_scalar(label, field, text)


def flat_rows(fields: tuple, values: dict | None) -> list[Row]:
    """A received message as an echo shows it: nested messages (not compact ones) are opened down to
    their fields, so every row is a value, a compact message or a list, named by its path
    ('pose.pose.position'). A field missing from `values` has the value None (nothing received)."""
    rows: list[Row] = []

    def walk(node: Any, path: Path, value: Any) -> None:
        shape = shape_of(node)
        if shape != MESSAGE or not node.children:
            rows.append(Row(path, node, 0, shape, value))
            return
        for child in node.children:
            walk(child, path + (child.name,), value.get(child.name) if isinstance(value, dict) else None)

    for node in fields:
        walk(node, (node.name,), (values or {}).get(node.name))
    return rows


def readable(value: Any) -> Any:
    """`value` with every float cut to ECHO_DISPLAY_DIGITS significant digits, for display only
    (1.0806046117362795 -> 1.0806); a float's whole part is never cut (1728036001.5 -> 1728036002.0)."""
    if isinstance(value, dict):
        return {key: readable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [readable(item) for item in value]
    if isinstance(value, float) and math.isfinite(value) and value != 0.0:
        return round(value, max(0, ECHO_DISPLAY_DIGITS - 1 - math.floor(math.log10(abs(value)))))
    return value


def flat_text(row: Row) -> str:
    """A flat row's value on one line, as an echo shows it: a list as its items, `[1.0, 2.0, …]`, and
    floats cut to readable digits (`readable`; the row's value keeps them all)."""
    if row.shape == LEAF and is_string(row.label):
        return row.text
    return flow_yaml(readable(row.value))


def _get(values: dict, path: Path) -> Any:
    for part in path:
        values = values[part]
    return values


def _put(values: dict, path: Path, value: Any) -> None:
    _get(values, path[:-1])[path[-1]] = value


def _compact_parents(nodes: tuple, path: Path) -> list[Path]:
    """The nested messages (not inside a list) whose fields are all compact rows, such as a Pose's
    position and orientation: they start unfolded, so the compact rows read as one flat form."""
    found = []
    for node in nodes:
        if shape_of(node) != MESSAGE or not node.children:
            continue
        here = path + (node.name,)
        if all(shape_of(child) == COMPACT for child in node.children):
            found.append(here)
        else:
            found += _compact_parents(node.children, here)
    return found


class FieldRows:
    """The rows of one message: its value, which rows are unfolded, and the edits to them."""

    def __init__(self, fields: tuple, values: dict | None, editable: bool = True):
        self.fields = tuple(fields)
        self.values = copy.deepcopy(values) if values else {}
        self.editable = editable
        self._opened: set[Path] = set()
        self._rows: list[Row] | None = None  # rows(), until a value or a fold changes (`_changed`).
        self._index: dict[Path, int] = {}  # Each row's index by path, alongside `_rows`.
        self.bad = ''  # The field the last send check rejected (shown in red), or ''.
        top = self.rows()
        if len(top) == 1 and top[0].folds and self._has_children(top[0]):  # One nested message: unfolded.
            self._opened.add(top[0].path)
        self._opened.update(_compact_parents(self.fields, ()))
        self._changed()

    # ---------- rows ----------
    def rows(self) -> list[Row]:
        """The rows as shown, top to bottom (kept until a value or a fold changes)."""
        if self._rows is None:
            rows: list[Row] = []
            for node in self.fields:
                value = self.values[node.name] if node.name in self.values else default_value(node)
                self._walk(node, (node.name,), 0, value, rows)
            self._rows, self._index = rows, {row.path: index for index, row in enumerate(rows)}
        return self._rows

    def _changed(self) -> None:
        """Every change to `values` or `_opened` goes through here, so rows() is built again."""
        self._rows = None

    def _walk(self, node: Any, path: Path, depth: int, value: Any, rows: list[Row]) -> None:
        shape = shape_of(node)
        is_open = shape in (MESSAGE, ARRAY) and path in self._opened
        rows.append(Row(path, node, depth, shape, value, is_open))
        if not is_open:
            return
        if shape == MESSAGE:
            for child in node.children:
                item = value[child.name] if isinstance(value, dict) and child.name in value else default_value(child)
                self._walk(child, path + (child.name,), depth + 1, item, rows)
            return
        element = element_of(node)
        for index, item in enumerate(value or ()):
            self._walk(element, path + (index,), depth + 1, item, rows)

    def row(self, index: int) -> Row | None:
        rows = self.rows()
        return rows[index] if 0 <= index < len(rows) else None

    def index_of(self, path: Path | str) -> int | None:
        path = parse_path(path) if isinstance(path, str) else path
        self.rows()
        return self._index.get(path)

    def has_folds(self) -> bool:
        return any(shape_of(node) in (MESSAGE, ARRAY) for node in self.fields)

    # ---------- values ----------
    def get(self, path: Path) -> Any:
        return _get(self.values, path)

    def to_plain(self) -> dict:
        return copy.deepcopy(self.values)

    def load(self, values: dict) -> None:
        """Replace the whole value (undo, a history step); what is unfolded stays."""
        self.values = copy.deepcopy(values)
        self.bad = ''
        self._changed()

    def accept(self, index: int, text: str, validate: Callable[[dict], Any] | None = None) -> tuple[Any, Any]:
        """Keep `text` as the value of row `index`: (old value, new value). Raises ValueError with
        the user's message when it doesn't parse, or when `validate` (build_message over the whole
        message) reports a FieldError at or inside this row."""
        row = self.row(index)
        value = parse(row, text)
        if validate is not None:
            candidate = copy.deepcopy(self.values)
            _put(candidate, row.path, value)
            try:
                validate(candidate)
            except Exception as error:  # noqa: BLE001 - a FieldError, matched by its path
                path = getattr(error, 'path', None)
                if path is None:
                    raise
                if within(path, row.field):
                    raise ValueError(describe(error, text.strip())) from None
        _put(self.values, row.path, value)
        self._changed()
        if within(self.bad, row.field) or within(row.field, self.bad):
            self.bad = ''
        return row.value, value

    # ---------- folding ----------
    def toggle(self, index: int) -> str | None:
        """enter on a MESSAGE or ARRAY row: unfold or fold it. The log line, or None for other rows."""
        row = self.row(index)
        if row is None or not row.folds:
            return None
        if row.open:
            self._fold(row.path, False)
            return f'folded {row.field}'
        if not self._has_children(row):
            return f'{row.field} is empty' + (' — o adds an element' if row.shape == ARRAY and self.editable else '')
        self._fold(row.path, True)
        return f'unfolded {row.field}'

    def fold(self, index: int) -> tuple[int, str] | None:
        """h / ←: fold an unfolded row, else go up to the parent row. None at the top level."""
        row = self.row(index)
        if row is None:
            return None
        if row.open:
            self._fold(row.path, False)
            return index, f'folded {row.field}'
        if row.depth == 0:
            return None
        parent = row.path[:-1]
        return self.index_of(parent), f'up to {path_text(parent)}'

    def unfold(self, index: int) -> tuple[int, str] | None:
        """l / →: unfold a folded row, or step into an unfolded one. None on a row without fields."""
        row = self.row(index)
        if row is None or not row.folds:
            return None
        if not self._has_children(row):
            return index, f'{row.field} is empty'
        if not row.open:
            self._fold(row.path, True)
            return index, f'unfolded {row.field}'
        return index + 1, f'into {row.field}'

    def _fold(self, path: Path, unfolded: bool) -> None:
        if unfolded:
            self._opened.add(path)
        else:
            self._opened.discard(path)
        self._changed()

    def _has_children(self, row: Row) -> bool:
        return bool(row.value) if row.shape == ARRAY else bool(row.node.children)

    def reveal(self, field: str) -> int:
        """Unfold what hides `field` (a FieldError path) and return the row that shows it: the field
        itself, or the compact row or list it is inside."""
        path = parse_path(field)
        for depth in range(1, len(path)):
            index = self.index_of(path[:depth])
            row = self.row(index) if index is not None else None
            if row is None or not row.folds:
                break
            self._fold(row.path, True)
        for depth in range(len(path), 0, -1):
            index = self.index_of(path[:depth])
            if index is not None:
                return index
        return 0

    # ---------- list elements ----------
    def _element_path(self, row: Row) -> Path | None:
        """The path of the list element `row` is (or is inside), or None."""
        for depth in range(len(row.path) - 1, 0, -1):
            if isinstance(row.path[depth], int):
                return row.path[:depth + 1]
        return None

    def _array_row(self, path: Path) -> Row:
        return self.row(self.index_of(path))

    def add_item(self, index: int) -> Path:
        """o: add an element after the one under the cursor, or at the end on the list's own row.
        Returns the new element's path; ValueError with the user's message when it can't."""
        row = self.row(index)
        element = self._element_path(row) if row else None
        if row is not None and row.shape == ARRAY:
            array, at = row, len(row.value or ())
        elif element is not None:
            array, at = self._array_row(element[:-1]), element[-1] + 1
        else:
            raise ValueError('o adds to a list — move the cursor to one ([…] rows)')
        info = array_info(array.label)
        items = self.get(array.path)
        if info.size is not None:
            raise ValueError(f'{array.field} always has {info.size} elements')
        if info.bound is not None and len(items) >= info.bound:
            raise ValueError(f'{array.field} holds at most {info.bound} elements')
        self._shift(array.path, at, 1)
        items.insert(at, default_value(element_of(array.node)))
        self._fold(array.path, True)
        return array.path + (at,)

    def delete_item(self, index: int) -> tuple[Path, Path]:
        """d: delete the element under the cursor. Returns (its path, the path the cursor goes to);
        ValueError with the user's message when it can't."""
        row = self.row(index)
        element = self._element_path(row) if row else None
        if element is None:
            raise ValueError('d deletes a list element — move the cursor to one ([0], [1] …)')
        array = self._array_row(element[:-1])
        info = array_info(array.label)
        if info.size is not None:
            raise ValueError(f'{array.field} always has {info.size} elements')
        items = self.get(array.path)
        at = element[-1]
        del items[at]
        self._shift(array.path, at + 1, -1)
        self._changed()
        if at < len(items):
            return element, element
        return element, array.path + (at - 1,) if items else array.path

    def _shift(self, array: Path, start: int, delta: int) -> None:
        """Keep unfolded elements unfolded when the ones before them are added or deleted."""
        size = len(array)
        moved = set()
        for path in self._opened:
            inside = path[:size] == array and len(path) > size
            if inside and path[size] >= start:
                moved.add(path[:size] + (path[size] + delta,) + path[size + 1:])
            elif not (inside and delta < 0 and path[size] == start - 1):  # Drop a deleted element's.
                moved.add(path)
        self._opened = moved
