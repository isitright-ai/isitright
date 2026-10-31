"""Paths inside JSON values: ``orders.items[*].price`` names the price of every item of an order.

A path is a field of a collection (``orders.items``) followed by keys and list wildcards
(``[*]``). A declared shape (a small JSON Schema subset on a field of type ``json``) lists the
leaves the field is known to hold. Both give the JSON family a scope; without either it proposes
nothing.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from typing import Any

from isitright.core.entities import ModelError

WILD = "*"
_TOKEN = re.compile(r"\[(\*|\d+)\]|\.?([A-Za-z_][\w-]*)")
NUMERIC_SHAPES = {"number", "integer"}

JsonPath = list[str | int]
"""Keys and list indexes from the root of the JSON value; ``"*"`` stands for any index."""


def split_hint_path(path: str) -> tuple[str, str, list[str | int]]:
    """``orders.items[*].price`` -> (``orders``, ``items``, ``["*", "price"]``)."""
    collection, _, rest = path.partition(".")
    if not collection or not rest:
        raise ModelError(f"JSON path {path!r} must look like 'collection.field[*].leaf'")
    tokens = parse_tokens(rest)
    if not tokens or not isinstance(tokens[0], str) or tokens[0] == WILD:
        raise ModelError(f"JSON path {path!r} must name a field after the collection")
    return collection, str(tokens[0]), tokens[1:]


def parse_tokens(text: str) -> list[str | int]:
    out: list[str | int] = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise ModelError(f"cannot read JSON path {text!r} at {text[position:]!r}")
        index, key = match.groups()
        out.append(key if key is not None else (WILD if index == WILD else int(index)))
        position = match.end()
    return out


def concrete_paths(value: Any, path: JsonPath) -> Iterator[tuple[JsonPath, Any]]:
    """Every concrete (path, value) that ``path`` covers in ``value``."""
    if not path:
        yield [], value
        return
    head, rest = path[0], path[1:]
    if head == WILD or isinstance(head, int):
        if not isinstance(value, list):
            return
        indexes = range(len(value)) if head == WILD else [head]
        for i in indexes:
            if isinstance(i, int) and 0 <= i < len(value):
                for tail, leaf in concrete_paths(value[i], rest):
                    yield [i, *tail], leaf
    elif isinstance(value, dict) and head in value:
        for tail, leaf in concrete_paths(value[head], rest):
            yield [head, *tail], leaf


def get_at(value: Any, path: JsonPath) -> Any:
    for token in path:
        value = value[token]
    return value


def set_at(value: Any, path: JsonPath, new: Any) -> Any:
    """A deep copy of ``value`` with the leaf at ``path`` replaced."""
    out = copy.deepcopy(value)
    if not path:
        return copy.deepcopy(new)
    holder = get_at(out, path[:-1])
    holder[path[-1]] = copy.deepcopy(new)
    return out


def remove_at(value: Any, path: JsonPath) -> Any:
    """A deep copy of ``value`` without the key or list element at ``path``."""
    out = copy.deepcopy(value)
    holder = get_at(out, path[:-1])
    if isinstance(holder, list):
        index = path[-1]
        assert isinstance(index, int)
        del holder[index]
    else:
        holder.pop(path[-1], None)
    return out


def duplicate_at(value: Any, path: JsonPath) -> Any:
    """A deep copy of ``value`` with the list element at ``path`` repeated right after itself."""
    out = copy.deepcopy(value)
    holder = get_at(out, path[:-1])
    index = path[-1]
    assert isinstance(holder, list) and isinstance(index, int)
    holder.insert(index + 1, copy.deepcopy(holder[index]))
    return out


def shape_leaf(shape: dict[str, Any] | None, path: JsonPath) -> dict[str, Any] | None:
    """The shape of the node a path leads to, or None when the shape does not describe it."""
    node = shape
    for token in path:
        if node is None:
            return None
        if token == WILD or isinstance(token, int):
            node = node.get("items") if node.get("type") == "array" else None
        else:
            props = node.get("properties") if node.get("type") == "object" else None
            node = props.get(token) if isinstance(props, dict) else None
    return node


def numeric_leaves(shape: dict[str, Any], prefix: JsonPath | None = None) -> list[JsonPath]:
    """Paths (with wildcards) of the numeric leaves a shape declares."""
    prefix = prefix or []
    kind = shape.get("type")
    if kind in NUMERIC_SHAPES:
        return [prefix]
    if kind == "array" and isinstance(shape.get("items"), dict):
        return numeric_leaves(shape["items"], [*prefix, WILD])
    if kind == "object" and isinstance(shape.get("properties"), dict):
        out: list[JsonPath] = []
        for name, inner in shape["properties"].items():
            if isinstance(inner, dict):
                out.extend(numeric_leaves(inner, [*prefix, name]))
        return out
    return []


def text_of(path: JsonPath) -> str:
    out = ""
    for token in path:
        out += f"[{token}]" if token == WILD or isinstance(token, int) else f".{token}"
    return out
