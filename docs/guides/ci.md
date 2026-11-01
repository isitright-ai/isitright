# Use in CI

isitright can fail a build when an audit finds evidence strong enough to act on. The default policy
never fails.

## Policies

| Pack | Flag | Fails (exit code 3) when |
|---|---|---|
| SQL | `--fail-on domain-counterexample` | A [`COUNTEREXAMPLE_FOUND`](../concepts/evidence.md#divergence_status) is [`DOMAIN_VALIDATED`](../concepts/validity-and-fidelity.md#validity-tiers) |
| SQL | `--fail-on any-counterexample` | Any `COUNTEREXAMPLE_FOUND` |
| Agents | `--fail-on invariant-violation` | A run violated an invariant |
| Agents | `--fail-on any-finding` | Any finding |
| Both | `--fail-on none` (default) | Never |

An **emulated** SQL finding that no native run verified never fails CI. A finding that PostgreSQL
confirmed (`verified_on: NATIVE_ISOLATED`) may. A divergence that does not reproduce natively is an
emulation artifact and does not count. `--no-verify-native` turns verification off, and then
emulated findings never fail.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Completed |
| `1` | Internal error, or `INCONCLUSIVE` |
| `2` | Invalid input, including no valid world, or `--max-money` with an agent that reports no cost |
| `3` | The opt-in `--fail-on` policy triggered |

## SQL suite on every change

```yaml
name: sql-audit
on: [pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install isitright
      - run: >
          isitright sql suite --database data/shop.sqlite --cases evals/shop.jsonl
          --constraints rules/shop.yaml --output-dir artifacts/sql-audit
          --fail-on domain-counterexample -q
      - if: always()
        uses: actions/upload-artifact@v4
        with: {name: sql-audit, path: artifacts/sql-audit}
```

Upload the report directory whether or not the job fails, so a reviewer can open `suite_report.md`
and [replay](replay-and-export.md) the counterexample.

## Live agents in CI

A live-agent audit costs money and is noisy. If you run one in CI:

- set `--max-money`, `--max-runs` and `--max-seconds` so a bad day cannot run away;
- use `--worlds fixed` or a pinned list of `--world` ids for a stable regression check, and
  generated worlds on a schedule rather than on every pull request;
- prefer `--fail-on invariant-violation`. An observed invariant violation is evidence about a run.
  `any-finding` also fails when the expected behavior was not reached, which is a broader and
  noisier signal.

Replay exported [eval cases](replay-and-export.md#export) offline in CI instead: `rerun_eval_case` calls no agent and costs nothing.
