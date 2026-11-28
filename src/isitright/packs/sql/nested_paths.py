"""Which paths inside a nested column a query reads (per-path scoping, 0.9).

0.7 scoped generation and the `nested_edit` family to the nested *columns* a query reads, so a
query that reads only ``items[].qty`` still had the whole ``items`` column generated and mutated,
``sku`` and every other field included. This module resolves each nested reference to a path inside
its column, so generation and mutation can stay on the fields a query reads.

A path is a tuple of steps: a struct field name, ``[]`` for the elements of an array, and a final
``*`` meaning "this node and everything below it". ``("[]", "qty", "*")`` is the ``qty`` field of
every element; ``("*",)`` is the whole column, which is also what every reference that cannot be
resolved gets (a star projection, a map, a value passed on whole to a function, an alias that is
not understood). Falling back to the whole column never loses a counterexample: it only gives up
the narrowing, which is the 0.7 behaviour.

Resolved: dot access (``t.s.a``), array subscripts (``items[OFFSET(0)].qty``), ``UNNEST`` aliases
in ``FROM``, ``CROSS JOIN`` and ``LEFT JOIN`` (BigQuery ``AS i``; Presto and Trino ``AS u(a, b)``,
the columns of a row element in order), an ``UNNEST`` of an alias (arrays inside arrays), and
columns that a CTE or a derived table passes through unchanged (``WITH x AS (SELECT items ...)``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlglot import exp

from isitright.core.jsonpaths import WILD
from isitright.packs.sql.schema import DatabaseSchema
from isitright.packs.sql.typetree import TypeNode, leaf_value, minimal_value

NestedPath = tuple[str, ...]
ELEMENT = "[]"
ALL = "*"
WHOLE: NestedPath = (ALL,)

Column = tuple[str, str]
"""``(table, column)`` of a nested column."""


@dataclass(frozen=True)
class _Base:
    """Where an expression points: a nested column and a path inside it."""

    column: Column
    path: NestedPath


def nested_paths(
    trees: Iterable[exp.Query], db: DatabaseSchema
) -> dict[Column, frozenset[NestedPath]]:
    """The paths each query reads, per nested column, united over ``trees``. A nested column that
    no query reads is absent; one read whole maps to ``{("*",)}``."""
    types = {
        (t.name, c.name): c.type_tree
        for t in db.tables
        for c in t.columns
        if c.type_tree is not None and c.type_tree.nested
    }
    found: dict[Column, set[NestedPath]] = defaultdict(set)
    for tree in trees:
        for column, paths in _Resolver(tree, db, types).run().items():
            found[column] |= paths
    return {column: _normalize(paths) for column, paths in found.items()}


def _normalize(paths: set[NestedPath]) -> frozenset[NestedPath]:
    """Drop the paths that a subtree path (one ending in ``*``) already covers."""
    stems = [p[:-1] for p in paths if p and p[-1] == ALL]
    return frozenset(
        p for p in paths if not any(p != (*s, ALL) and p[: len(s)] == s for s in stems)
    )


class _Resolver:
    def __init__(self, tree: exp.Query, db: DatabaseSchema, types: dict[Column, TypeNode]) -> None:
        self.tree = tree
        self.types = types
        self.tables: dict[str, str] = {}
        for table in tree.find_all(exp.Table):
            if table.name in {t.name for t in db.tables}:
                self.tables[table.alias_or_name] = table.name
                self.tables[table.name] = table.name
        self.aliases: dict[str, list[_Base]] = defaultdict(list)
        """An unqualified name (an UNNEST alias, a CTE or derived-table output) to its bases."""
        self.relations: dict[str, dict[str, list[_Base]]] = defaultdict(dict)
        """A qualifier (Presto's ``u`` in ``AS u(a, b)``, a CTE name) to its columns' bases."""
        self.passed: set[int] = set()
        """ids of expressions that pass a nested value through unchanged (not reads)."""
        self.found: dict[Column, set[NestedPath]] = defaultdict(set)

    # --- the type at a path ---------------------------------------------------------------------

    def node_at(self, base: _Base) -> TypeNode | None:
        node: TypeNode | None = self.types.get(base.column)
        for step in base.path:
            if node is None:
                return None
            if step == ELEMENT:
                node = node.element if node.kind == "ARRAY" else None
            else:
                node = (
                    next((t for n, t, _ in node.fields if n == step), None)
                    if (node.kind == "STRUCT")
                    else None
                )
        return node

    def step(self, base: _Base, name: str) -> _Base | None:
        node = self.node_at(base)
        if node is None or node.kind != "STRUCT":
            return None
        if not any(n == name for n, _, _ in node.fields):
            return None
        return _Base(base.column, (*base.path, name))

    # --- resolving an expression to the bases it points at ---------------------------------------

    def resolve(self, node: exp.Expression) -> list[_Base] | None:
        """The bases a column chain points at; ``[]`` when it is not nested; None when it is
        nested but cannot be followed (the caller then reads the whole column)."""
        if isinstance(node, exp.Column):
            parts = [
                p.name
                for p in (node.args.get("catalog"), node.args.get("db"), node.args.get("table"))
                if p is not None
            ] + [node.name]
            return self._from_parts(parts)
        if isinstance(node, exp.Dot):
            inner = self.resolve(node.this)
            if inner is None:
                return None
            name = node.expression.name if isinstance(node.expression, exp.Expression) else ""
            out = []
            for base in inner:
                stepped = self.step(base, name)
                if stepped is None:
                    return None
                out.append(stepped)
            return out
        if isinstance(node, exp.Bracket):
            inner = self.resolve(node.this)
            if inner is None:
                return None
            out = []
            for base in inner:
                at = self.node_at(base)
                if at is None or at.kind != "ARRAY":
                    return None  # a map subscript, or something not understood
                out.append(_Base(base.column, (*base.path, ELEMENT)))
            return out
        return []

    def _from_parts(self, parts: list[str]) -> list[_Base] | None:
        head, rest = parts[0], parts[1:]
        bases: list[_Base] = []
        if head in self.relations and rest and rest[0] in self.relations[head]:
            bases, rest = list(self.relations[head][rest[0]]), rest[1:]
        elif head in self.relations and rest:
            return []  # a plain column of a CTE or of an UNNEST relation
        elif head in self.aliases:
            bases = list(self.aliases[head])
        elif head in self.tables and rest:
            column = (self.tables[head], rest[0])
            if column not in self.types:
                return []
            bases, rest = [_Base(column, ())], rest[1:]
        else:
            named = [c for c in self.types if c[1] == head]
            if not named:
                return []
            bases = [_Base(c, ()) for c in named]
        for name in rest:
            stepped = [self.step(b, name) for b in bases]
            if any(s is None for s in stepped):
                return None
            bases = [s for s in stepped if s is not None]
        return bases

    # --- the passes -----------------------------------------------------------------------------

    def run(self) -> dict[Column, set[NestedPath]]:
        if self._has_star():
            return {column: {WHOLE} for column in self._columns_of_tables()}
        for _ in range(4):  # aliases can depend on aliases (arrays inside arrays)
            before = {k: list(v) for k, v in self.aliases.items()}
            self._unnest_aliases()
            self._pass_through()
            if before == {k: list(v) for k, v in self.aliases.items()}:
                break
        for node in self.tree.find_all(exp.Column, exp.Dot, exp.Bracket):
            if self._extended(node) or id(node) in self.passed:
                continue
            bases = self.resolve(node)
            if bases is None:
                self._whole(node)
                continue
            for base in bases:
                self.found[base.column].add((*base.path, ALL))
        return dict(self.found)

    def _extended(self, node: exp.Expression) -> bool:
        """True when ``node`` is the inner part of a longer chain (``a`` in ``a.b`` or ``a[0]``)."""
        parent = node.parent
        return isinstance(parent, exp.Dot | exp.Bracket) and parent.this is node

    def _whole(self, node: exp.Expression) -> None:
        """A nested reference that cannot be followed: every column it might name, whole."""
        column = node.find(exp.Column)
        if column is None:
            return
        parts = [
            p.name
            for p in (column.args.get("catalog"), column.args.get("db"), column.args.get("table"))
            if p is not None
        ] + [column.name]
        head = parts[0]
        if head in self.aliases:
            for base in self.aliases[head]:
                self.found[base.column].add(WHOLE)
            return
        if head in self.tables and len(parts) > 1:
            column_key = (self.tables[head], parts[1])
            if column_key in self.types:
                self.found[column_key].add(WHOLE)
            return
        for key in self.types:
            if key[1] == head:
                self.found[key].add(WHOLE)

    def _unnest_aliases(self) -> None:
        for unnest in self.tree.find_all(exp.Unnest):
            if not unnest.expressions:
                continue
            argument = unnest.expressions[0]
            bases = self.resolve(argument)
            self.passed.add(id(argument))
            if bases is None or not bases:
                if bases is None:
                    self._whole(argument)
                continue
            arrays = [b for b in bases if (n := self.node_at(b)) is not None and n.kind == "ARRAY"]
            if len(arrays) != len(bases):
                for base in bases:
                    self.found[base.column].add(WHOLE)
                continue
            for base in arrays:  # the array itself is read: its elements exist or not
                self.found[base.column].add(base.path)
            elements = [_Base(b.column, (*b.path, ELEMENT)) for b in arrays]
            alias = unnest.args.get("alias")
            if not isinstance(alias, exp.TableAlias):
                continue
            columns = [c.name for c in alias.columns]
            if not alias.name and len(columns) == 1:  # BigQuery: AS i names the element
                self._alias(columns[0], elements)
            elif columns:  # Presto and Trino: AS u(a, b), a row's fields or the element
                self._row_columns(alias.name, columns, elements)
            elif alias.name:
                self._alias(alias.name, elements)

    def _row_columns(self, relation: str, columns: list[str], elements: list[_Base]) -> None:
        for base in elements:
            node = self.node_at(base)
            if node is not None and node.kind == "STRUCT" and len(node.fields) == len(columns):
                named = [
                    (name, _Base(base.column, (*base.path, field)))
                    for name, (field, _, _) in zip(columns, node.fields, strict=True)
                ]
            elif len(columns) == 1:
                named = [(columns[0], base)]
            else:
                self.found[base.column].add(WHOLE)
                continue
            for name, target in named:
                self._alias(name, [target])
                if relation:
                    self.relations[relation].setdefault(name, [])
                    if target not in self.relations[relation][name]:
                        self.relations[relation][name].append(target)

    def _alias(self, name: str, bases: list[_Base]) -> None:
        for base in bases:
            if base not in self.aliases[name]:
                self.aliases[name].append(base)

    def _pass_through(self) -> None:
        """A CTE or derived-table projection that is a nested chain, with or without an alias:
        its output name points where the chain points, and the projection is not itself a read."""
        for select in self.tree.find_all(exp.Select):
            owner = select.parent
            if not isinstance(owner, exp.CTE | exp.Subquery) or not owner.alias:
                continue
            for projection in select.expressions:
                inner = projection.this if isinstance(projection, exp.Alias) else projection
                if not isinstance(inner, exp.Column | exp.Dot | exp.Bracket):
                    continue
                bases = self.resolve(inner)
                if not bases:
                    continue
                self.passed.add(id(inner))
                name = projection.alias_or_name
                self._alias(name, bases)
                known = self.relations[owner.alias].setdefault(name, [])
                known.extend(b for b in bases if b not in known)

    def _has_star(self) -> bool:
        for star in self.tree.find_all(exp.Star):
            if isinstance(star.parent, exp.Count):
                continue
            return True
        return any(
            isinstance(c, exp.Column) and isinstance(c.this, exp.Star)
            for c in self.tree.find_all(exp.Column)
        )

    def _columns_of_tables(self) -> set[Column]:
        read = set(self.tables.values())
        return {c for c in self.types if c[0] in read}


# --- scope tests used by generation and the mutation family ------------------------------------


def in_scope(path: NestedPath, paths: frozenset[NestedPath]) -> bool:
    """True when the node at ``path`` is read: it lies on the way to a read path, or under a
    subtree path."""
    for read in paths:
        if read and read[-1] == ALL:
            stem = read[:-1]
            if path[: len(stem)] == stem or stem[: len(path)] == path:
                return True
        elif read[: len(path)] == path:
            return True
    return False


def describe(paths: frozenset[NestedPath]) -> list[str]:
    """Text for the report: ``*`` for a whole column, ``[*].qty`` for a subtree that is read, and
    ``[*].tags (array only)`` for an array whose elements are iterated but not read by that path."""
    out = []
    for path in sorted(paths):
        if path == WHOLE:
            out.append("*")
            continue
        subtree = bool(path) and path[-1] == ALL
        steps = path[:-1] if subtree else path
        text = "".join("[*]" if step == ELEMENT else f".{step}" for step in steps)
        out.append(text if subtree else f"{text or '(column)'} (array only)")
    return out


def json_steps(path: list[str | int]) -> NestedPath:
    """A path of the core's JSON family (``["*", "qty"]``, wildcards or indexes) as steps."""
    return tuple(ELEMENT if step == WILD or isinstance(step, int) else str(step) for step in path)


def scoped_value(node: TypeNode, paths: frozenset[NestedPath], where: NestedPath = ()) -> Any:
    """The base value of a nested column with only the read paths filled in.

    A node on a read path is generated as in 0.7 (an array holds one element, so emptying it is a
    change); a struct field off every read path is NULL where it may be, else its smallest value.
    """
    if node.kind == "ARRAY" and node.element is not None:
        inner = (*where, ELEMENT)
        if in_scope(inner, paths):
            return [scoped_value(node.element, paths, inner)]
        return [minimal_value(node.element, populate=False)]
    if node.kind == "STRUCT":
        out = {}
        for name, inner_type, not_null in node.fields:
            inner = (*where, name)
            if in_scope(inner, paths):
                out[name] = scoped_value(inner_type, paths, inner)
            else:
                out[name] = minimal_value(inner_type, populate=False) if not_null else None
        return out
    if node.kind == "MAP":
        return minimal_value(node, populate=True)
    return leaf_value(node)
