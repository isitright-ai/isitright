# Synthetic fixture proposal — owner review required

These files' purpose is to make intended semantics reviewable without allowing an implementation to silently invent its own oracle.

## Proposed corpus

- `synthetic_logistics.sql` creates the shared SQLite schema and seed rows.
- `null_count_minimal_counterexample.sql` is an independently authored one-row
  reproduction for `COUNT(*)` versus `COUNT(nullable_column)`.
- `constraints.yaml` is a standard JSON Schema Draft 2020-12 document describing
  valid normalized database snapshots.
- `synthetic_acceptance_cases.jsonl` contains 17 independently authored cases.
  Five are marked `deliberate_latent_divergence: true`; it is an end-to-end
  acceptance fixture, not a benchmark or a copy of the private experiment.
- `fixture_expectations.yaml` is a test-only oracle describing expected future
  outcomes. It is never accepted as runtime user input.

## Approval checklist

- Confirm that unordered results preserve duplicate multiplicity.
- Confirm that automatic ordering follows only a top-level `ORDER BY` on the
  reference query.
- Confirm that the one-row shipment reproduction captures the intended NULL
  behavior and that the JSON Schema describes admissible logistics data.
- Confirm that native SQLite window expressions are executable; bounded agreement
  does not imply a dedicated window-specific search strategy or equivalence proof.
- Review whether each generated state would be plausible under the declared rules.
- Confirm that no private experiment case, natural-language question, identifier,
  constant, or row appears in the public corpus. Keep private validation separate.
- Approve all expected statuses while keeping attribution `UNDETERMINED`.

## Owner-reviewed semantics

- `log-003` is retained as an intentional multiplicity ambiguity. The owner considers
  `DISTINCT` the more defensible interpretation because “every hub zone” suggests a
  list of unique zones, while recognizing that the wording does not state uniqueness
  explicitly. The counterexample demonstrates a real disagreement; it does not
  establish candidate fault, and core attribution remains `UNDETERMINED`.
- `log-014` uses native SQLite window execution and expects
  `AGREEMENT_ON_TESTED_STATES`. Version 0.1 has no window-specific mutation family,
  so this status remains bounded evidence rather than an equivalence proof.
- `log-005` admits a delivered shipment whose `shipped_at` value is unknown. The
  synthetic domain treats `status` as authoritative and permits incomplete timestamp
  data, so timestamp presence must not be assumed equivalent to delivered status.
  The disagreement does not establish candidate fault, and core attribution remains
  `UNDETERMINED`.

