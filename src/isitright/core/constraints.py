"""Constraint language: declarative data that both checks states and guides generation.

The canonical form is a small set of classes that serialize to JSON (``Range``, ``OneOf``,
``NotNull``, ``Unique``, ``FunctionalDependency``, ``Aggregate`` and row-level expressions). Python
predicates are an escape hatch: they check, but no generator can read them, and reports list them.

Row-level expressions use one small syntax everywhere (constraints and hint ``where`` clauses):
bare names are fields of the row, ``@name`` is a state parameter, ``$name`` is the value of another
hint, and ``a.b`` reads an attribute of a hint value.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from isitright.core.entities import (
    NUMERIC_TYPES,
    CollectionSpec,
    EntitySchema,
    ModelError,
    parse_instant,
)
from isitright.core.world import Atom, Entity, State


class ValidityTier(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    DOMAIN_VALIDATED = "DOMAIN_VALIDATED"
    REACHABLE = "REACHABLE"
    TASK_CONSISTENT = "TASK_CONSISTENT"
    OBSERVABLE = "OBSERVABLE"
    SIMULATOR_CONSISTENT = "SIMULATOR_CONSISTENT"


class ValidityStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    INDETERMINATE = "INDETERMINATE"
    NOT_ASSESSED = "NOT_ASSESSED"


@dataclass(frozen=True)
class Domain:
    """Values a field may take, for generators to aim at."""

    minimum: Any = None
    maximum: Any = None
    min_exclusive: bool = False
    max_exclusive: bool = False
    values: tuple[Any, ...] | None = None


# --- row-level expressions ----------------------------------------------------------------------

_REF = re.compile(r"([$@])([A-Za-z_]\w*)")
_COMPARE: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_ARITH: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "len": len,
    "lower": lambda s: s.lower(),
    "instant": parse_instant,
}


@dataclass(frozen=True)
class ExprEnv:
    """What an expression can read: the row's collection, state parameters and hint values."""

    collection: CollectionSpec | None = None
    params: Mapping[str, Any] | None = None
    hints: Mapping[str, Any] | None = None


class Expression:
    """A parsed, restricted row-level expression."""

    def __init__(self, text: str) -> None:
        self.text = text
        try:
            self._tree = ast.parse(
                _REF.sub(lambda m: f"__{(m[1] == '$' and 'h') or 'p'}_{m[2]}", text), mode="eval"
            )
        except SyntaxError as error:
            raise ModelError(f"bad expression {text!r}: {error.msg}") from error
        if "__" in _REF.sub("", text):
            raise ModelError(f"expression {text!r} may not use double underscores")
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Call) and not (
                isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS
            ):
                raise ModelError(f"expression {text!r} calls an unsupported function")
            if not isinstance(node, _ALLOWED):
                raise ModelError(
                    f"expression {text!r} uses unsupported syntax: {type(node).__name__}"
                )

    def names(self) -> set[str]:
        """Bare field names the expression reads."""
        return {
            n.id
            for n in ast.walk(self._tree)
            if isinstance(n, ast.Name)
            and not n.id.startswith(("__h_", "__p_"))
            and n.id not in _FUNCTIONS
        }

    def hint_refs(self) -> set[str]:
        return {
            n.id[4:]
            for n in ast.walk(self._tree)
            if isinstance(n, ast.Name) and n.id.startswith("__h_")
        }

    def evaluate(self, row: Entity, env: ExprEnv) -> Any:
        return self._eval(self._tree.body, row, env)

    def holds(self, row: Entity, env: ExprEnv) -> bool:
        return bool(self.evaluate(row, env))

    def _eval(self, node: ast.expr, row: Entity, env: ExprEnv) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._name(node.id, row, env)
        if isinstance(node, ast.Attribute):
            base = self._eval(node.value, row, env)
            if isinstance(base, list):
                return [b.get(node.attr) if isinstance(b, dict) else None for b in base]
            return base.get(node.attr) if isinstance(base, dict) else None
        if isinstance(node, ast.BoolOp):
            values = (self._eval(v, row, env) for v in node.values)
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp):
            value = self._eval(node.operand, row, env)
            return (not value) if isinstance(node.op, ast.Not) else -value
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left, row, env), self._eval(node.right, row, env)
            if left is None or right is None:
                return None
            return _ARITH[type(node.op)](_number(left), _number(right))
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, row, env)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._eval(comparator, row, env)
                if not _compare(type(op), left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.List | ast.Tuple):
            return [self._eval(e, row, env) for e in node.elts]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return _FUNCTIONS[node.func.id](*(self._eval(a, row, env) for a in node.args))
        raise ModelError(f"cannot evaluate {ast.dump(node)}")  # pragma: no cover

    def _name(self, name: str, row: Entity, env: ExprEnv) -> Any:
        if name.startswith("__h_"):
            hints = env.hints or {}
            if name[4:] not in hints:
                raise ModelError(f"expression {self.text!r} refers to unknown hint ${name[4:]}")
            return hints[name[4:]]
        if name.startswith("__p_"):
            return _typed_param((env.params or {}).get(name[4:]))
        value = row.get(name)
        if value is not None and env.collection is not None:
            try:
                kind = env.collection.field(name).type
            except ModelError:
                kind = "json"
            if kind in {"date", "datetime"}:
                return parse_instant(value)
        return value


_ALLOWED = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Call,
)


def _typed_param(value: Any) -> Any:
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        try:
            return parse_instant(value)
        except ValueError:
            return value
    return value


def _number(value: Any) -> Any:
    return Decimal(value) if isinstance(value, str) else value


def _compare(op: type[ast.cmpop], left: Any, right: Any) -> bool:
    if op in (ast.In, ast.NotIn):
        return _COMPARE[op](left, right if isinstance(right, list | tuple | str) else [right])
    if left is None or right is None:
        return (op is ast.Eq and left is right) or (op is ast.NotEq and left is not right)
    if isinstance(right, list) and op is ast.Eq:
        return left in right
    if isinstance(left, datetime) and isinstance(right, str):
        right = parse_instant(right)
    elif isinstance(right, datetime) and isinstance(left, str):
        left = parse_instant(left)
    try:
        return _COMPARE[op](left, right)
    except TypeError:
        return False


# --- constraint classes ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    tier: Literal["STRUCTURAL", "DOMAIN_VALIDATED"] = "DOMAIN_VALIDATED"

    def label(self) -> str:
        return self.name or self.describe()

    def describe(self) -> str:
        raise NotImplementedError

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        raise NotImplementedError

    def paths(self) -> list[str]:
        """Field paths the rule reads, so loading can reject a rule that does not resolve."""
        return []

    def value_domain(self, path: str) -> Domain | None:
        return None


def values_at(schema: EntitySchema, state: State, path: str) -> Iterator[tuple[Atom, Any, bool]]:
    """(owning atom, value, present) for each entity a dotted field path covers."""
    parts = path.split(".")
    spec = schema.collection(parts[0])
    for entity in state.entities(spec.name):
        atom = (spec.name, entity[spec.key])
        level: list[Entity] = [entity]
        for part in parts[1:-1]:
            level = [inner for e in level for inner in (e.get(part) or {}).values()]
        for item in level:
            yield atom, item.get(parts[-1]), parts[-1] in item


class NotNull(_Base):
    kind: Literal["not_null"] = "not_null"
    path: str

    def describe(self) -> str:
        return f"{self.path} is not null"

    def paths(self) -> list[str]:
        return [self.path]

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        return [
            Violation(self.label(), f"{atom} has no {self.path}")
            for atom, value, _ in values_at(schema, state, self.path)
            if value is None
        ]


class Range(_Base):
    kind: Literal["range"] = "range"
    path: str
    min: Any = None
    max: Any = None
    min_exclusive: bool = False
    max_exclusive: bool = False

    def describe(self) -> str:
        low = "-inf" if self.min is None else self.min
        high = "inf" if self.max is None else self.max
        return f"{self.path} in {'(' if self.min_exclusive else '['}{low}, {high}" + (
            ")" if self.max_exclusive else "]"
        )

    def paths(self) -> list[str]:
        return [self.path]

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        out: list[Violation] = []
        _, spec = schema.resolve(self.path)
        for atom, value, _ in values_at(schema, state, self.path):
            if value is None:
                continue
            v: Any = parse_instant(value) if spec.type in {"date", "datetime"} else _plain(value)
            low = self._bound(self.min, spec.type)
            high = self._bound(self.max, spec.type)
            if low is not None and (v < low or (self.min_exclusive and v == low)):
                out.append(
                    Violation(self.label(), f"{atom}.{self.path}={value!r} is below {self.min}")
                )
            if high is not None and (v > high or (self.max_exclusive and v == high)):
                out.append(
                    Violation(self.label(), f"{atom}.{self.path}={value!r} is above {self.max}")
                )
        return out

    @staticmethod
    def _bound(bound: Any, kind: str) -> Any:
        if bound is None:
            return None
        return parse_instant(bound) if kind in {"date", "datetime"} else _plain(bound)

    def value_domain(self, path: str) -> Domain | None:
        if path != self.path:
            return None
        return Domain(self.min, self.max, self.min_exclusive, self.max_exclusive)


def _plain(value: Any) -> Any:
    return Decimal(value) if isinstance(value, str) else value


class OneOf(_Base):
    kind: Literal["one_of"] = "one_of"
    path: str
    values: list[Any]

    def describe(self) -> str:
        return f"{self.path} in {self.values}"

    def paths(self) -> list[str]:
        return [self.path]

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        return [
            Violation(self.label(), f"{atom}.{self.path}={value!r} is not in {self.values}")
            for atom, value, present in values_at(schema, state, self.path)
            if present and value is not None and value not in self.values
        ]

    def value_domain(self, path: str) -> Domain | None:
        return Domain(values=tuple(self.values)) if path == self.path else None


class Unique(_Base):
    kind: Literal["unique"] = "unique"
    collection: str
    fields: list[str]

    def describe(self) -> str:
        return f"{self.collection}({', '.join(self.fields)}) is unique"

    def paths(self) -> list[str]:
        return [f"{self.collection}.{f}" for f in self.fields]

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        seen: set[tuple[Any, ...]] = set()
        out: list[Violation] = []
        for entity in state.entities(self.collection):
            combo = tuple(entity.get(f) for f in self.fields)
            if None in combo:
                continue
            if combo in seen:
                out.append(Violation(self.label(), f"{self.collection} repeats {combo}"))
            seen.add(combo)
        return out


class FunctionalDependency(_Base):
    kind: Literal["functional_dependency"] = "functional_dependency"
    collection: str
    determinant: list[str]
    dependent: list[str]

    def describe(self) -> str:
        return f"{self.collection}: {self.determinant} determines {self.dependent}"

    def paths(self) -> list[str]:
        return [f"{self.collection}.{f}" for f in [*self.determinant, *self.dependent]]

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        seen: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        out: list[Violation] = []
        for entity in state.entities(self.collection):
            left = tuple(entity.get(f) for f in self.determinant)
            right = tuple(entity.get(f) for f in self.dependent)
            if seen.setdefault(left, right) != right:
                out.append(Violation(self.label(), f"{self.collection}: {left} maps to two values"))
        return out


class Aggregate(_Base):
    """``agg(child.child_field) op parent.parent_field`` over the children of each parent.

    The Split family reads this rule to build children that satisfy it.
    """

    kind: Literal["aggregate"] = "aggregate"
    parent: str
    child: str
    via: str
    """The child field that references the parent's key."""
    child_field: str
    parent_field: str
    agg: Literal["sum", "count"] = "sum"
    op: Literal["==", "<=", ">="] = "=="
    tolerance: float = 1e-9

    def describe(self) -> str:
        child = f"{self.child}.{self.child_field}"
        return f"{self.agg}({child}) {self.op} {self.parent}.{self.parent_field}"

    def paths(self) -> list[str]:
        return [
            f"{self.parent}.{self.parent_field}",
            f"{self.child}.{self.child_field}",
            f"{self.child}.{self.via}",
        ]

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        parent_key = schema.collection(self.parent).key
        totals: dict[Any, Decimal] = {}
        for entity in state.entities(self.child):
            amount = (
                Decimal(1) if self.agg == "count" else _plain(entity.get(self.child_field) or 0)
            )
            owner = entity.get(self.via)
            totals[owner] = totals.get(owner, Decimal(0)) + Decimal(str(amount))
        out: list[Violation] = []
        tol = Decimal(str(self.tolerance))
        for entity in state.entities(self.parent):
            total = totals.get(entity[parent_key], Decimal(0))
            wanted = Decimal(str(entity.get(self.parent_field) or 0))
            ok = {
                "==": abs(total - wanted) <= tol,
                "<=": total <= wanted + tol,
                ">=": total >= wanted - tol,
            }[self.op]
            if not ok:
                out.append(
                    Violation(
                        self.label(),
                        f"{self.parent}[{entity[parent_key]!r}]: {self.agg} of {self.child}."
                        f"{self.child_field} is {total}, {self.parent_field} is {wanted}",
                    )
                )
        return out


class RowExpr(_Base):
    kind: Literal["row"] = "row"
    collection: str
    expr: str

    def describe(self) -> str:
        return f"{self.collection}: {self.expr}"

    def paths(self) -> list[str]:
        return [f"{self.collection}.{n}" for n in Expression(self.expr).names()]

    def check(self, schema: EntitySchema, state: State) -> list[Violation]:
        spec = schema.collection(self.collection)
        expression = Expression(self.expr)
        env = ExprEnv(spec, state.params)
        return [
            Violation(self.label(), f"{self.collection}[{e[spec.key]!r}] violates {self.expr}")
            for e in state.entities(self.collection)
            if not expression.holds(e, env)
        ]


Constraint = Annotated[
    NotNull | Range | OneOf | Unique | FunctionalDependency | Aggregate | RowExpr,
    Field(discriminator="kind"),
]
_CONSTRAINTS = TypeAdapter(list[Constraint])


def constraints_from_json(data: list[dict[str, Any]]) -> list[Constraint]:
    return _CONSTRAINTS.validate_python(data)


def constraints_to_json(constraints: list[Constraint]) -> list[dict[str, Any]]:
    return list(_CONSTRAINTS.dump_python(constraints, mode="json", exclude_none=True))


@dataclass(frozen=True)
class PythonConstraint:
    """Check-only escape hatch. No generator can read it, so reports list it as unused."""

    name: str
    check_fn: Callable[[State], list[str]]
    description: str = ""
    tier: str = "DOMAIN_VALIDATED"


@dataclass(frozen=True)
class Validity:
    status: ValidityStatus
    tiers: tuple[ValidityTier, ...]
    problems: tuple[str, ...] = ()
    checked_rules: tuple[str, ...] = ()
    check_only_rules: tuple[str, ...] = ()


def check_constraints(
    schema: EntitySchema,
    constraints: list[Constraint],
    python_constraints: list[PythonConstraint],
    state: State,
) -> Validity:
    """Structural checks from the schema, then every declared rule. INVALID beats everything."""
    problems = list(schema.check_structural(state))
    checked = ["schema:keys_types_references"]
    domain_rules = 0
    for constraint in constraints:
        checked.append(constraint.label())
        violations = constraint.check(schema, state)
        problems.extend(f"{v.rule}: {v.message}" for v in violations)
        domain_rules += constraint.tier == "DOMAIN_VALIDATED"
    undecided: list[str] = []
    for rule in python_constraints:
        checked.append(rule.name)
        domain_rules += rule.tier == "DOMAIN_VALIDATED"
        try:
            problems.extend(f"{rule.name}: {message}" for message in rule.check_fn(state))
        except Exception as error:  # a check-only rule that cannot decide is not a pass
            undecided.append(f"{rule.name} raised {type(error).__name__}: {error}")
    if undecided and not problems:
        return Validity(
            ValidityStatus.INDETERMINATE,
            (),
            tuple(undecided),
            tuple(checked),
            tuple(r.name for r in python_constraints),
        )
    if problems:
        return Validity(
            ValidityStatus.INVALID,
            (),
            tuple(problems),
            tuple(checked),
            tuple(r.name for r in python_constraints),
        )
    tiers = [ValidityTier.STRUCTURAL]
    if domain_rules:
        tiers.append(ValidityTier.DOMAIN_VALIDATED)
    return Validity(
        ValidityStatus.VALID,
        tuple(tiers),
        (),
        tuple(checked),
        tuple(r.name for r in python_constraints),
    )


def check_paths(schema: EntitySchema, constraints: list[Constraint]) -> None:
    """Reject, at load time, a constraint that names a collection or field the model lacks."""
    for constraint in constraints:
        for path in constraint.paths():
            schema.resolve(path)
        if isinstance(constraint, Unique | FunctionalDependency | RowExpr | Aggregate):
            schema.collection(
                constraint.parent if isinstance(constraint, Aggregate) else constraint.collection
            )


def field_domain(constraints: list[Constraint], path: str) -> Domain | None:
    """The first declared value domain for a path, if any rule offers one."""
    for constraint in constraints:
        domain = constraint.value_domain(path)
        if domain is not None:
            return domain
    return None


def numeric_field(schema: EntitySchema, path: str) -> bool:
    return schema.resolve(path)[1].type in NUMERIC_TYPES
