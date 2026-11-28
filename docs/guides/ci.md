# Use in CI

isitright can fail a build when an audit finds evidence strong enough to act on. The default policy
never fails.

## Policies

| Pack | Flag | Fails (exit code 3) when |
|---|---|---|
| SQL | `--fail-on domain-counterexample` | A [`COUNTEREXAMPLE_FOUND`](../concepts/evidence.md#divergence_status) is [`DOMAIN_VALIDATED`](../concepts/validity-and-fidelity.md#validity-tiers) |
| SQL | `--fail-on any-counterexample` | Any `COUNTEREXAMPLE_FOUND` |
| Agents | `--fail-on invariant-violation` | A finding graded `RATE_INCREASE` involves an invariant violation |
| Agents | `--fail-on any-finding` | A finding graded `RATE_INCREASE` (the same as `rate-increase`) |
| Agents, research, data (live) | `--fail-on rate-increase` | A paired test decided a higher failure rate: status `COUNTEREXAMPLE_FOUND` (research also accepts `any-counterexample`, which means the same for a live agent) |
| Agents, research, data (live) | `--fail-on observed-failure` | Also a failure observed on a world that ran and was not found invalid, with no rate decision: status `OBSERVED_FAILURE` |
| Both | `--fail-on none` (default) | Never |

An **emulated** SQL finding that no native run verified never fails CI. A finding that PostgreSQL
confirmed (`verified_on: NATIVE_ISOLATED`) may. A divergence that does not reproduce natively is an
emulation artifact and does not count. `--no-verify-native` turns verification off, and then
emulated findings never fail.

### Live-agent gates

**The default is `--fail-on none`.** Completing an audit never fails CI just because it found evidence.
A rate-based gate is something you choose.

A live-agent finding has one of two grades. `RATE_INCREASE`: a paired sequential test decided that the world
fails more often than the baseline. `OBSERVED_FAILURE`: a judged run failed on a mutated world that ran and was
not found invalid, and no test decided a higher rate. Both are shown in the report. The gates keep them apart:

| Choose | When | Fails (exit 3) on |
|---|---|---|
| `--fail-on rate-increase` (recommended for generated-world CI) | You want a build to fail only on a supported change in the failure rate | A decided `RATE_INCREASE`. One failed run of an agent that fails at random does not break the build |
| `--fail-on observed-failure` (stricter) | Zero tolerance, or a fixed regression set that must never fail | Any finding, an observation included |
| `--fail-on any-finding`, `--fail-on invariant-violation` (agents), `--fail-on any-counterexample` (research) | As before 0.9 | Only a rate increase (an observation never trips them); `invariant-violation` narrows it to findings that involve an invariant |
| `--fail-on none` (default) | | Never |

`agents run`, `research check` and `data audit` take these options. A world marked `NOT_ASSESSED` was not
validated (a fixed world without a validator): a gate on it rests on the world as run, and the report says so.
The shared vocabulary across all four packs, with aliases, is N10.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Completed |
| `1` | Internal error; a replay that did not reproduce; or `INCONCLUSIVE` from `agents run` or from `sql check` on PostgreSQL or DuckDB (a SQLite check that is `INCONCLUSIVE` exits `0`) |
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

!!! warning "Reports and agent logs can hold secrets"
    An `agents run` output directory holds `agent.log` (the agent's stdout and stderr) and the
    recorded traces for every run. The agent command runs with the job's environment, so a log can
    contain tokens the agent printed or a tool echoed. Do not upload that directory as a public or
    widely readable artifact without checking it, and prefer uploading `report.md` and `report.json`.

Upload the report directory whether or not the job fails, so a reviewer can open `suite_report.md`
and [replay](replay-and-export.md) the counterexample.

## Live agents in CI

A live-agent audit costs money and is noisy. If you run one in CI:

- set `--max-money`, `--max-runs` and `--max-seconds` so a bad day cannot run away (since 0.9 the default run
  stopping rule waits for 10% of the ranked worlds, so a quiet search goes on longer than before and costs more
  runs unless these are set);
- use `--worlds fixed` or a pinned list of `--world` ids for a stable regression check, and
  generated worlds on a schedule rather than on every pull request;
- prefer `--fail-on rate-increase` for generated worlds: it needs a paired test. For a pinned list of
  worlds that must never fail, `--fail-on observed-failure` is the stricter gate. `invariant-violation`
  narrows the rate-increase gate to findings that involve an invariant.

Replay exported [eval cases](replay-and-export.md#export) offline in CI instead: `rerun_eval_case` calls no agent and costs nothing.
