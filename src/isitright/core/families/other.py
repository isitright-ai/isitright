"""Prior operations, response edits and timing."""

from __future__ import annotations

from collections.abc import Iterator

from isitright.core.families._util import scoped_entities
from isitright.core.families.state import Boundary, ReferenceSwap
from isitright.core.hints import Hint, Hints
from isitright.core.mutations import (
    Mutation,
    ResponseEdit,
    SetField,
    Trigger,
    World,
    edits_between,
)
from isitright.core.spec import WorldSpec


class PriorOperation:
    """Apply one of the service's own write operations before the run (reachable)."""

    family = "prior_operation"
    target = "state"
    consumes = frozenset({"scope", "lookup"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        state = world.state
        scope_atoms = {
            (collection, entity[state.keys[collection]])
            for collection in {h.args["collection"] for h in hints.of("scope")}
            for entity in scoped_entities(spec, state, hints, collection)[0]
        }
        scope_names = [h.name for h in hints.of("scope")]
        for operation in spec.operations:
            for arguments in operation.options(state):
                result = operation.apply(state, arguments)
                if result is None or result == state:
                    continue
                edits = edits_between(state, result)
                touched = operation.touches(arguments)
                hinted = bool(scope_atoms) and any(a in scope_atoms for a in touched)
                yield Mutation(
                    family=self.family,
                    description=f"prior operation {operation.name}({_args(arguments)})",
                    edits=edits,
                    atoms=touched,
                    hints=scope_names if hinted else [],
                    touches=sorted({_touch(e) for e in edits}),
                    reachable=True,
                )


def _args(arguments: dict[str, object]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in arguments.items())


def _touch(edit: object) -> str:
    collection = getattr(edit, "collection", None)
    if collection is None:
        return f"params.{getattr(edit, 'name', '')}"
    path = getattr(edit, "path", None)
    return f"{collection}.{path[0]}" if path else f"{collection}.*"


class ResponseEdits:
    """Edits to what one tool call returns; the state is unchanged."""

    family = "response_edit"
    target = "response"
    consumes = frozenset({"trace"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        called = {call["tool"] for hint in hints.of("trace") for call in hint.args.get("calls", [])}
        names = [h.name for h in hints.of("trace")]
        for tool in spec.tools:
            hinted = names if tool.name in called else []
            if tool.writes:
                yield self._edit(
                    ResponseEdit(
                        tool=tool.name,
                        op="empty_ack",
                        first_only=True,
                        declares=f"the first successful {tool.name} happened; its reply is empty",
                    ),
                    f"the first successful {tool.name} returns an empty acknowledgement",
                    hinted,
                )
                continue
            if tool.list_field:
                yield self._edit(
                    ResponseEdit(
                        tool=tool.name,
                        op="reorder",
                        field=tool.list_field,
                        declares=f"{tool.name} lists the same items in a different order",
                    ),
                    f"{tool.name} returns {tool.list_field} in another order",
                    hinted,
                )
            for list_name in tool.nested_lists:
                yield self._edit(
                    ResponseEdit(
                        tool=tool.name,
                        op="drop_field",
                        field=list_name,
                        declares=f"the {list_name} exist but {tool.name} does not show them",
                    ),
                    f"{tool.name} shows no {list_name}",
                    hinted,
                )

    @staticmethod
    def _edit(edit: ResponseEdit, description: str, hint_names: list[str]) -> Mutation:
        return Mutation(
            family="response_edit",
            target="response",
            description=description,
            response=edit,
            hints=hint_names,
        )


class Timing:
    """A state edit that fires after a matching call seen in the baseline trace.

    The edits come from the Boundary family on gate hints (a status moves one step), so a world can
    change under the agent between a read and a write.
    """

    family = "timing"
    target = "timing"
    consumes = frozenset({"trace", "gate", "scope"})

    def propose(self, spec: WorldSpec, world: World, hints: Hints) -> Iterator[Mutation]:
        reads = {t.name for t in spec.tools if not t.writes}
        calls: list[tuple[Hint, dict[str, object]]] = [
            (hint, call)
            for hint in hints.of("trace")
            for call in hint.args.get("calls", [])
            if call["tool"] in reads
        ]
        seen: set[tuple[str, str]] = set()
        inner_mutations = [
            *Boundary().propose(spec, world, hints),
            *ReferenceSwap().propose(spec, world, hints),
        ]
        for inner in inner_mutations:
            if len(inner.edits) != 1 or not isinstance(inner.edits[0], SetField) or not inner.hints:
                continue
            for hint, call in calls:
                match = dict(call.get("arguments", {}))  # type: ignore[call-overload]
                key = (
                    str(call["tool"]),
                    repr(sorted(match.items())) + repr(inner.edits[0].value) + repr(inner.atoms),
                )
                if key in seen:
                    continue
                seen.add(key)
                yield Mutation(
                    family=self.family,
                    target="timing",
                    description=f"{inner.description}, right after {call['tool']}({_args(match)})",
                    edits=inner.edits,
                    trigger=Trigger(tool=str(call["tool"]), match=match),
                    atoms=inner.atoms,
                    hints=[*inner.hints, hint.name],
                    touches=inner.touches,
                )
