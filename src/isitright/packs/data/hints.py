"""Hints for a data-analysis task, from the program, the schema and the question text.

Never from the gold answers. From a recorded program (``ast``): the files it reads, the columns it
names, the literals and thresholds it compares columns with, the sort and group keys. From the
question text: the columns it names (provenance ``harvested:question``). Hints only prioritize
mutations; they never decide that a world is valid.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from isitright.core.entities import EntitySchema
from isitright.core.hints import Hint, Hints, Provenance
from isitright.packs.data.mapping import ROW_KEY, TableFile, column_name, field_name

_NUMERIC = {"int", "float"}
_COMPARISON = {
    ast.Gt: ("above", False),
    ast.GtE: ("above", True),
    ast.Lt: ("below", False),
    ast.LtE: ("below", True),
}
_FLIP = {ast.Gt: ast.Lt, ast.GtE: ast.LtE, ast.Lt: ast.Gt, ast.LtE: ast.GtE}
_SORTS = {"sort_values", "nlargest", "nsmallest", "idxmax", "idxmin", "drop_duplicates", "rank"}
_GROUPS = {"groupby", "pivot_table", "value_counts", "crosstab"}


@dataclass
class _Harvest:
    schema: EntitySchema
    files: dict[str, str]
    tables_read: list[str] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)
    hints: dict[str, Hint] = field(default_factory=dict)

    def add(self, kind: str, name: str, args: dict[str, Any], provenance: Provenance) -> None:
        if name not in self.hints:
            self.hints[name] = Hint(kind=kind, name=name, provenance=provenance, args=args)

    def tables_for(self, variable: str | None) -> list[str]:
        if variable is not None and variable in self.variables:
            return [self.variables[variable]]
        return self.tables_read

    def column_in(self, tables: list[str], name: str) -> list[str]:
        """Tables with a column of this name (as the program spells it)."""
        alias = field_name(name)
        return [
            t
            for t in tables
            if alias != ROW_KEY and any(f.name == alias for f in self.schema.collection(t).fields)
        ]

    def field_type(self, table: str, name: str) -> str:
        return self.schema.collection(table).field(name).type


def harvest_program_hints(
    code: str, schema: EntitySchema, files: list[TableFile], *, question: str = ""
) -> Hints:
    """Declare hints for one task from its program and, optionally, its question text."""
    harvest = _Harvest(schema, {f.file: f.table for f in files})
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return Hints()
    _tables(tree, harvest)
    for table in harvest.tables_read:
        harvest.add("scope", f"scope:{table}", {"collection": table}, Provenance.HARVESTED_PROGRAM)
    _columns(tree, harvest)
    _comparisons(tree, harvest)
    _orderings(tree, harvest)
    if question:
        _question(question, harvest)
    return Hints(harvest.hints.values())


def _tables(tree: ast.AST, h: _Harvest) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str) and value in h.files and h.files[value] not in h.tables_read:
                h.tables_read.append(h.files[value])
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if call.args and isinstance(call.args[0], ast.Constant):
                table = h.files.get(str(call.args[0].value))
                for target in node.targets:
                    if table and isinstance(target, ast.Name):
                        h.variables[target.id] = table
    if not h.tables_read:
        h.tables_read.extend(h.files.values())


def _names(node: ast.AST) -> list[str]:
    """Column-like names an expression mentions: string constants and attribute names."""
    found = []
    for inner in ast.walk(node):
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            found.append(inner.value)
        elif isinstance(inner, ast.Attribute):
            found.append(inner.attr)
    return found


def _columns(tree: ast.AST, h: _Harvest) -> None:
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            names = [node.value]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        for name in names:
            for table in h.column_in(h.tables_read, name):
                h.add(
                    "column",
                    f"column:{table}.{field_name(name)}",
                    {"collection": table, "field": field_name(name)},
                    Provenance.HARVESTED_PROGRAM,
                )
        if isinstance(node, ast.Call) and _call_name(node) in _GROUPS:
            for name in _call_columns(node):
                for table in h.column_in(h.tables_read, name):
                    h.add(
                        "scope",
                        f"scope:{table}",
                        {"collection": table},
                        Provenance.HARVESTED_PROGRAM,
                    )


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _call_columns(call: ast.Call) -> list[str]:
    out: list[str] = []
    for arg in [*call.args, *(k.value for k in call.keywords)]:
        out.extend(n for n in _names(arg) if isinstance(n, str))
    return out


def _column_ref(node: ast.expr, h: _Harvest) -> tuple[list[str], str] | None:
    """``df['c']`` or ``df.c``: the tables that could own it and the column name."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        name, base = node.slice.value, node.value
    elif isinstance(node, ast.Attribute):
        name, base = node.attr, node.value
    else:
        return None
    if not isinstance(name, str):
        return None
    variable = base.id if isinstance(base, ast.Name) else None
    tables = h.column_in(h.tables_for(variable), name)
    return (tables, name) if tables else None


def _literal_hint(h: _Harvest, table: str, name: str, value: Any) -> None:
    name = field_name(name)
    kind = h.field_type(table, name)
    numeric = isinstance(value, int | float) and not isinstance(value, bool)
    if (numeric and kind in _NUMERIC) or (isinstance(value, str) and kind in {"text"}):
        h.add(
            "literal",
            f"literal:{table}.{name}={value!r}",
            {"path": f"{table}.{name}", "value": value},
            Provenance.HARVESTED_PROGRAM,
        )


def _threshold_hint(h: _Harvest, table: str, name: str, value: Any, op: type[ast.cmpop]) -> None:
    name = field_name(name)
    if not (isinstance(value, int | float) and not isinstance(value, bool)):
        return
    if h.field_type(table, name) not in _NUMERIC or op not in _COMPARISON:
        return
    holds, inclusive = _COMPARISON[op]
    h.add(
        "threshold",
        f"threshold:{table}.{name}{'>=' if holds == 'above' and inclusive else ''}{value!r}",
        {
            "path": f"{table}.{name}",
            "value": value,
            "holds": holds,
            "inclusive": inclusive,
        },
        Provenance.HARVESTED_PROGRAM,
    )


def _comparisons(tree: ast.AST, h: _Harvest) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right, op = node.left, node.comparators[0], type(node.ops[0])
            ref, const = _column_ref(left, h), right
            if ref is None:
                ref, const = _column_ref(right, h), left
                op = _FLIP.get(op, op)
            if ref is not None and isinstance(const, ast.Constant):
                for table in ref[0]:
                    _literal_hint(h, table, ref[1], const.value)
                    _threshold_hint(h, table, ref[1], const.value, op)
        if isinstance(node, ast.Call) and _call_name(node) in {"isin", "between"}:
            ref = _column_ref(node.func.value, h) if isinstance(node.func, ast.Attribute) else None
            if ref is None:
                continue
            for arg in node.args:
                values = (
                    [e.value for e in arg.elts if isinstance(e, ast.Constant)]
                    if isinstance(arg, ast.List | ast.Tuple | ast.Set)
                    else [arg.value]
                    if isinstance(arg, ast.Constant)
                    else []
                )
                for table in ref[0]:
                    for value in values:
                        _literal_hint(h, table, ref[1], value)
        if isinstance(node, ast.Call) and _call_name(node) == "query" and node.args:
            _query(node.args[0], h)


def _query(arg: ast.expr, h: _Harvest) -> None:
    """``df.query("price > 3 and kind == 'a'")``: bare names are columns."""
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return
    try:
        expression = ast.parse(arg.value, mode="eval")
    except SyntaxError:
        return
    for node in ast.walk(expression):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right, op = node.left, node.comparators[0], type(node.ops[0])
            if isinstance(right, ast.Name) and isinstance(left, ast.Constant):
                left, right, op = right, left, _FLIP.get(op, op)
            if isinstance(left, ast.Name) and isinstance(right, ast.Constant):
                for table in h.column_in(h.tables_read, left.id):
                    _literal_hint(h, table, left.id, right.value)
                    _threshold_hint(h, table, left.id, right.value, op)


def _orderings(tree: ast.AST, h: _Harvest) -> None:
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _call_name(node) in _SORTS):
            continue
        name = _call_name(node)
        descending = name in {"nlargest", "idxmax"} or any(
            k.arg == "ascending" and isinstance(k.value, ast.Constant) and k.value.value is False
            for k in node.keywords
        )
        for column in _call_columns(node):
            for table in h.column_in(h.tables_read, column):
                h.add(
                    "ordering",
                    f"ordering:{table}.{field_name(column)}",
                    {
                        "collection": table,
                        "field": field_name(column),
                        "direction": "desc" if descending else "asc",
                    },
                    Provenance.HARVESTED_PROGRAM,
                )


def _question(question: str, h: _Harvest) -> None:
    words = set(re.findall(r"[A-Za-z0-9_]+", question.lower()))
    for table in h.tables_read:
        for spec in h.schema.collection(table).fields:
            name = column_name(spec.name)
            if spec.name == ROW_KEY:
                continue
            if name.lower() in words or f'"{name}"' in question or f"'{name}'" in question:
                h.add(
                    "column",
                    f"column:{table}.{spec.name}",
                    {"collection": table, "field": spec.name},
                    Provenance.HARVESTED_QUESTION,
                )
