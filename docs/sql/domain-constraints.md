# Domain constraints

Without domain rules, isitright knows only what the schema says. A counterexample then reaches the
[`STRUCTURAL`](../concepts/validity-and-fidelity.md#validity-tiers) tier: keys, types, references and engine constraints hold. A reviewer can still say
"that row could never exist". Domain constraints are how you say what could never exist, so that
counterexamples reach `DOMAIN_VALIDATED` and absurd worlds are rejected before they run.

## Format

A JSON Schema document (Draft 2020-12), in YAML or JSON, describing the database as a snapshot:
one property per table, each an array of row objects.

```yaml
$schema: https://json-schema.org/draft/2020-12/schema
type: object
required: [tribute]
properties:
  tribute:
    type: array
    items:
      type: object
      required: [tribute_id, province]
      properties:
        tribute_id: {type: integer, minimum: 1}
        province: {type: string, enum: [north, south, east, west]}
        amount_owed: {type: [number, "null"], minimum: 0}
        amount_collected: {type: [number, "null"], minimum: 0}
```

Pass it with `--constraints rules.yaml` (or `constraints=` / `constraints_file=` in Python).

How it is used:

- The **whole document is enforced** as a check on every generated state, and again at every
  [minimization](../concepts/minimization-and-replay.md) step.
- Simple per-column keywords (`type`, `minimum`, `maximum`, `enum`, nullability) also **steer
  generation** toward their edges.
- Anything the generator cannot use is listed in the report as a check-only rule under "Rules
  generation could not use". The check still applies, but a rule that is hard to satisfy will cause
  more rejected candidates (see `search.rejected`).

SQL `CHECK` constraints in your DDL are enforced by the engine, and the simple forms (`col IN
(...)`, `col >= number`) also guide generation. Put a rule in DDL when the database enforces it, and
in the constraints file when it is a convention the data follows.

## What to write

Write rules the business **guarantees**, not rules the sample data happens to satisfy.

| Write | Do not write |
|---|---|
| `amount_owed >= 0` when the system forbids negatives | `amount_collected` is never NULL, because your 300 sample rows have none |
| An enum for a status column | A narrow range copied from the min and max of today's data |
| A format that an upstream system enforces | A rule that mirrors the query under test |

!!! warning "Over-constraining hides the bugs you are looking for"
    Observing that a column has no NULLs in your data does not make NULL impossible. A rule made from
    sample data will reject exactly the NULL, duplicate or boundary worlds that reveal fragile
    queries. If you are not sure the system guarantees it, leave it out. A `STRUCTURAL` counterexample
    that a domain expert dismisses costs a minute; a missing counterexample costs a wrong answer in
    production.

Rules that mined data *suggests* are a good source of questions for the people who own the data, not
a source of constraints.

## Rules that span rows or tables

A per-column JSON Schema cannot express "payments sum to the order total". For rules that cross
rows or tables, pass a trusted validator in Python:

```python
from isitright import check
from isitright.packs.sql.validation import (
    CandidateStateView, ValidationFinding, ValidatorResult, ValidatorStatus,
)


class CollectedWithinOwed:
    name = "collected-within-owed"

    def __call__(self, state: CandidateStateView) -> ValidatorResult:
        findings = [
            ValidationFinding(
                rule_id="collected_le_owed",
                message=f"tribute {row['tribute_id'].value}: collected more than owed",
            )
            for row in state.rows("tribute")
            if row["amount_owed"].value is not None
            and row["amount_collected"].value is not None
            and row["amount_collected"].value > row["amount_owed"].value
        ]
        return ValidatorResult(
            validator_name=self.name,
            status=ValidatorStatus.INVALID if findings else ValidatorStatus.VALID,
            checked_rules=["collected_le_owed"],
            findings=findings,
        )


report = check(database="example.sqlite", reference_sql=ref, candidate_sql=cand,
               validator=CollectedWithinOwed())
```

`state.rows(table)` yields one mapping per row. Each value is a `CanonicalValue`; read the Python
value from `.value`, which is `None` for SQL NULL. `state.engine` and `state.table_names()` are also
available.

A validator is arbitrary Python that runs on every candidate, so load it only from code you trust.
It is check-only: it rejects worlds but cannot steer generation, so a tight validator wastes budget
on rejected candidates (see `search.rejected`). If it raises an exception, or returns
`INDETERMINATE`, every candidate is rejected and the case reports that no generated state satisfied
the rules. The Python API is for validators; the CLI takes only a constraints file.

## Check your rules

Run the audit and read the "Validation checks" and "Rules generation could not use" sections of
`case_report.md`. Then read the counterexample's world. If a domain expert says it is possible,
the tier means something. If not, add the missing rule and rerun.

For help drafting the file, see [SQL setup with an LLM](../onboarding/sql.md).
