# Quick start: data analysis

You will audit two recorded programs against a small data task, read the counterexample,
[replay](../guides/replay-and-export.md) it and export it as an eval case. It runs offline: no API
key, no model call, nothing to download. The two programs are constructed stand-ins that were written
by hand for this page (not by an agent); the task is a six-row table and a reference program.

Run these from a clone of the repository (see [Install](index.md)), with the `data` extra:

```console
pip install "isitright[data]"
```

## 1. Look at the task

A task is a directory: the question, the data and the reference ("gold") program. This one is in
`examples/data/quickstart/orders`.

```text
task.yaml   id: orders; question: What is the mean amount of the north region? Round to 2 decimal places.
gold.py     the reference program
data/orders.csv
```

```text
order_id,region,amount
1,north,20.0
2,north,25.0
3,south,40.0
4,north,25.0
5,south,10.0
6,east,
```

The reference drops missing amounts, then takes the mean of the north rows:
`north = df[df["region"] == "north"]["amount"].dropna()`. On this data the answer is 23.33.

`examples/data/quickstart/programs.jsonl` holds two recorded programs, the code an agent would have
executed. Both print 23.33 on this table, so both match the reference on the original data. The
first divides the sum by the number of north rows (`sum() / len(north)`); the second uses
`.mean()`.

## 2. Audit the programs

```console
isitright data check examples/data/quickstart/orders --programs examples/data/quickstart/programs.jsonl \
  --trust-code --attempts 100 --reuse 50 --output artifacts/quick-start-data
```

```text
orders:run-1: COUNTEREXAMPLE_FOUND
orders:run-2: NOT_FOUND_WITHIN_BUDGET
2 program(s) checked, 1 with a minimized disagreement. Report: artifacts/quick-start-data
```

**What `--trust-code` means.** The recorded programs are code, and the audit runs them on your
machine. Without the flag nothing runs. With it, each run goes to a separate process with a
temporary directory, a scrubbed environment (no API keys), a timeout and a memory limit, and an
in-process hook that blocks network access, new processes and writes outside that directory. **This
is not a sandbox**: native extensions and `ctypes` get around the hook. Use the flag on programs you
trust, or inside a container or VM without network access. See [Data analysis](../data.md).

## 3. Read the finding

`artifacts/quick-start-data/report.md` says, for the first program:

```text
Program and reference diverge after a boundary mutation. Difference: answer[northmean]:
expected 25.0, got 12.5 (tolerance: question asks for 2 decimal places: one unit in the last place).
Gold answer: {'north_mean': 25.0}; program answer: {'north_mean': 12.5}.
```

The minimized world, `artifacts/quick-start-data/findings/orders_run-1_1/orders.csv`, has two rows:

```text
order_id,region,amount
4,north,25.0
6,north,
```

One row of the east region became north (the mutation) and it has a missing amount, which the
original file already allowed (row 6 has none). The reference averages the one known amount, 25.0.
The program divides 25.0 by 2 rows and gets 12.5. On the original data no north row is missing an
amount, so the two agreed.

What the report states beside the disagreement:

- **Comparison policy and its basis.** Numbers are compared with a tolerance of one unit in the last
  place of the decimals the question asks for (0.01), plus a margin of 2 ulps for floating-point
  noise; the basis is printed with the difference. A question that names no decimals gets a tolerance
  of floating-point noise only.
- **Validity: `STRUCTURAL`.** Types and keys hold. No domain rule vouches for the world: this task
  declares none (see `constraints.yaml` in [Data analysis](../data.md)), so a reader decides whether
  a missing amount in a north order is plausible. Here it is allowed by the original file.
- **Scope.** A frozen finding is about this program on this world, "not a statement about the agent".
  Attribution stays `UNDETERMINED`: the program, the reference or the question could be what is
  wrong.

## 4. Replay and export

```console
isitright data replay artifacts/quick-start-data/report.json --trust-code
```

```text
Reproduced both answers and the disagreement.
  every expected outcome reproduced
```

```console
isitright data export artifacts/quick-start-data/report.json --output artifacts/quick-start-data/export
```

```text
Exported 1 eval case(s) to artifacts/quick-start-data/export
```

The export directory holds `cases.jsonl` and, per case, the dataset, the question, the reference
program and the expected answer: a regression case for the next version of your agent.

## 5. The program that holds up

The second program, `.mean()`, ended `NOT_FOUND_WITHIN_BUDGET`: no disagreement in 96 of the 100
worlds tried (the report lists the executed worlds). **That does not mean it is correct.** It means
this search, with this budget, this seed and these generators, did not find a valid world where it
differs from the reference. A bigger budget, a different seed or a rule you declare may find one.
isitright never reports "not found" as "equivalent".

## 6. The live mode (described, not run here)

The frozen audit replays code an agent already wrote. `isitright data audit` confirms the findings
with the agent itself, which may write different code when it sees different data. That needs an
agent and a model, so it costs money and is not part of this page. The shape of the command, with
the caps you must set:

```text
isitright data audit TASK_DIR --agent module:Factory --pass-env OPENAI_API_KEY \
  --env-file path/to/keys.env --programs programs.jsonl --output out/live --trust-code \
  --max-runs 40 --max-money 0.3 --max-seconds 2400
```

`--env-file` reads only the variables named by `--pass-env`; keep the file out of any synced folder
and set a spending limit with your provider. See [Data analysis](../data.md) for the details and the
measured costs of the 0.6 runs.

## 7. Your own task

Make a directory with `task.yaml` (an id, the question, the data files), `gold.py` (sets `result` to
a mapping from answer names to values, as the example does) and the data. Record the programs your
agent executed as JSONL in the format shown in [Data analysis](../data.md#a-recorded-program), then
run step 2. To tell isitright what is plausible, add `constraints.yaml`: a finding then reaches the
`DOMAIN_VALIDATED` tier only if the world obeys your rules. Without rules every finding is
`STRUCTURAL` and you read the minimized table yourself, as above.
