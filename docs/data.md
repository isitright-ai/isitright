# Data analysis agents

The data pack audits agents that write and run Python over data files. It asks the same question as the other packs: is there a valid change to the data under which an answer that matched the reference on the original data stops matching? It reuses the core's entity model, mutation families, search, minimization, replay and report. Only the host, the comparators and the way hints are read from a program are new.

It needs the `data` extra:

```console
pip install 'isitright[data]'
```

## Two modes from one subject

**Frozen.** The code an agent executed in its baseline run is recorded (a *recorded program*) and replayed on many generated worlds. This is cheap: no model is called. A frozen finding is scoped to the program: "this program disagrees with the reference on this world". It says nothing about the agent until a live run confirms it.

**Live.** The frozen replay ranks generated worlds, and the agent itself is run on the ranked worlds under the budgets, stopping rules and sequential test of `isitright agents run`. A live result records where a candidate was found (the frozen program) and where it was verified (the agent's own runs). The agent may write different code once it sees different data, so the report counts the runs whose code changed.

The minimized world of a frozen finding is also run live, so that a counterexample small enough to read is checked against the agent.

## A task

A task is a directory:

```text
task.yaml          id, question, files, answer policy, output files
gold.py            the reference program
constraints.yaml   optional domain rules
hints.yaml         optional declared hints
data/              the data files (or data_dir in task.yaml)
```

```yaml
id: orders
question: What is the mean amount of the north region? Round to 2 decimal places.
files:
  - file: orders.csv        # a collection named orders; add key: id to use a column as the key
answer:                     # optional; defaults come from the question text
  abs_tol: 0.01
  basis: the question asks for two decimal places
```

The gold program is a reference implementation of the question. It runs on each mutated world with the same host as the program under test, so it follows the data. It sets `result` to the answer, a mapping from answer names to values:

```python
import pandas as pd
df = pd.read_csv("orders.csv")
north = df[df["region"] == "north"]["amount"].dropna()
result = {"north_mean": round(float(north.mean()), 2)}
```

The gold program is an implementation, not the truth. It can be wrong or ambiguous, and the report says so under the oracle's limits.

## A recorded program

One JSON object per line (`isitright-recorded-program`, version 0.6):

```json
{"format": "isitright-recorded-program", "version": "0.6", "task_id": "orders",
 "program_id": "run-1", "code": "import pandas as pd\n...",
 "answer": {"text": "@north_mean[23.33]", "source": "agent"},
 "source": {"kind": "agent", "agent": "smolagents", "model": "...",
            "library_versions": {"pandas": "2.2.3"}, "captured_at": "..."}}
```

`code` is everything the agent executed, in order. The program runs with its working directory set to a temporary directory that holds the task's files under their original names. Its answer is the last argument of `final_answer(...)` (the host provides that function, so smolagents code runs as it is), else the variable `result` (the PandasAI convention), else standard output. A mapping of named answers can be printed as `@name[value]` pairs, the form the InfiAgent-DABench questions use. A program that was not produced by an agent must say `"kind": "constructed_stand_in"`.

A program is replayed only if it reads only the task's files, uses no network and starts no processes (a static scan with `ast`, then an audit hook), gives the same answer twice on the original data, and agrees with the gold program on the original data. Otherwise the case is `UNSUPPORTED` or `INCONCLUSIVE`, with the reason. A narrative answer is `CANNOT_JUDGE`.

## The host and what it does not protect

Each run goes to a separate process with a fresh temporary directory, a scrubbed environment (no API keys or other variables are inherited), a wall-clock timeout and a memory limit (an address-space limit on POSIX, a Job Object on Windows). Nothing runs in the audit process, and nothing runs without `--trust-code` (`trust_code=True` in the API).

The Windows limit caps the memory one process may commit. The runner puts itself in the Job Object before it runs any program, because a virtualenv's `python.exe` can be a launcher (for example when uv made the environment from a Microsoft Store Python) whose child, the process that runs your code, would not be in a job the audit process creates. If the limit cannot be set the runner exits and the run is reported as an error, never as an unlimited run. A program that exceeds the limit ends with the status `memory`.

By default every run starts a new process (`--reuse 1`). `--reuse N` keeps a process for N runs. That is several times faster, but modules a program imported stay loaded, so one run can affect the next. The report records which was used.

**This is not a sandbox.** An audit hook in the child blocks network connections, new processes, writes outside the working directory and reads of existing files outside it and the Python installation. The hook catches ordinary Python code. Native extensions and `ctypes` get around it. Nothing limits CPU use other than the timeout, disk use inside the directory, or what a program can learn from the machine. On Windows there is no file system or network namespace at all. Run audits of programs you do not trust in a container or a virtual machine with no network.

Results are `NATIVE_ISOLATED`: the real interpreter and libraries in a separate process, with their versions recorded. A frozen replay on a pandas other than the recorded one is stated in the report.

## Worlds

A table is a collection, a row is an entity, and `__row` is a synthetic key (the position in the original file) unless the task names a key column. Mutations act on rows and cells, so the generic families (boundary, missing, duplicate, tie, empty, key collision, edge value, and the others) apply unchanged. The file is written from the state with the column order of the original, and the program reads it with its own `pd.read_csv`.

Conventions, decided once:

- A missing cell is `None` in a state and an empty field in the file. `NaN`, `NA` and `NaT` never appear in a state.
- Text that pandas reads back as missing (`NA`, `null`, `N/A`, `nan`, the empty string) cannot be written, so generation never proposes it.
- The physical dtypes of a mutated world are what pandas infers from the written file. An integer column that gains a missing value becomes `float64`, as it would for the agent.
- Floats are written with a decimal point, so a float column stays float.
- Dates and timestamps are text in the file.
- A dot in a column name is stored as U+2024 in the state and restored in the file.

Unsupported tables, with the reason in the report: more than 5000 rows, duplicate column names, a non-default index, mixed types in a column, and anything other than CSV and Parquet. Parquet needs the `parquet` extra.

## Comparison

The policy is explicit and goes into every report with its basis.

- **Numbers**: within `abs_tol + rel_tol * |expected|`. When the question asks for N decimal places the tolerance is one unit in the last place, because the two programs may round a boundary value differently; the basis says so. Otherwise it is floating-point noise. This is deliberately loose: a difference smaller than the tolerance is not found.
- **Text**: equal after trimming and case folding (`text: none` for exact).
- **Named answers**: names are compared after normalization, values by their kind. A bare value stands for a task with one named answer. A list equals the same items in a comma-separated string.
- **Frames**: columns, dtype kind, values; the index is ignored unless the policy says `strict`.
- **An undefined reference answer** (the mean of an empty column) is not compared: the world is inconclusive.

## Hints

Hints come from the program (`ast`), the schema and the question text, never from gold answers. A program yields `scope` (the files it reads), `column`, `literal` and `threshold` hints (constants compared with a column, with the side and inclusivity), and `ordering` hints (sort keys, `nlargest`, `idxmax`, `drop_duplicates`). The question text adds `column` hints with provenance `harvested:question`. Declared hints in `hints.yaml` use the core format. Model-proposed hints stay labeled `proposed` and never raise a validity tier.

## Constraints

Domain rules use the core constraint language (`range`, `one_of`, `not_null`, `unique`), declared in `constraints.yaml`. With no rules a finding is `STRUCTURAL` only. A pandera schema can be imported (extra `data-schema`):

```python
from isitright.packs.data.pandera_import import constraints_from_pandera
rules, notes = constraints_from_pandera("orders", schema)
```

`notes` lists each pandera check that has no equivalent and is therefore not checked.

## Commands

```console
isitright data check tasks/ --programs programs.jsonl --output out --trust-code
isitright data audit tasks/orders --agent my_module:make_agent --programs programs.jsonl \
    --output live --trust-code --pass-env OPENAI_API_KEY --max-runs 60
isitright data replay out/report.json --trust-code
isitright data export out/report.json --output cases
```

- `check` is the frozen audit. `--attempts` (default 300) bounds the worlds tried per program.
- `check` also takes `--cache DIR` and `--resume` for audits that may be interrupted (next section).
- `audit` is the live audit. `--agent module:callable` builds a `DataAgent` (see `isitright.packs.data.adapters`) in a separate process that receives only the variables named by `--pass-env`. `--max-runs`, `--max-money` and `--max-seconds` are budgets; `--max-worlds` is a safety rail; `--stratum-patience` and `--run-patience` are the stopping rules. A world the agent was not run on is listed as `NOT_RUN` with the reason. A money budget needs the agent to report its cost. `--env-file FILE` reads the `--pass-env` variables (for example an API key) from a dotenv-style file: only the named variables are used, a variable already in the environment wins, no value is printed, and the command refuses to start if a named variable is still not set. Keep that file out of version control and out of synced folders.
- `replay` reruns a finding from its concrete minimized world.
- `export` writes each finding as an eval case: the dataset as CSV, the question, the gold program and the expected answer.

## Long audits: resume and the run cache

A frozen audit of a large table can run for hours. Two flags on `check` keep a crash or a restart from losing it:

```console
isitright data check tasks/177 --programs programs.jsonl --output out/177 --trust-code \
    --attempts 500 --cache cache/
# interrupted? rerun the same command with --resume:
isitright data check tasks/177 --programs programs.jsonl --output out/177 --trust-code \
    --attempts 500 --cache cache/ --resume
```

- **Finished programs are saved** under `out/177/.resume` as each one completes. `--resume` keeps them as they were and audits only the rest. This works without `--cache`.
- **`--cache DIR`** also keeps each finished host run, keyed by the hash of the code and the fingerprint of the world. The search is deterministic for a seed and a budget, so a resumed program asks for the same worlds in the same order and takes finished runs from the cache instead of running them again. Only the check that two runs on the original data agree is made again, on purpose.
- **Results never depend on the cache.** A hit is a run already made on that exact world; a miss runs the program as usual. A cache file is tied to the host settings (timeout, memory limit, `--reuse`) and the installed packages, and starts afresh when either changes. Runs that ended in a timeout or the memory limit are not stored, because they depend on how loaded the machine was.
- **`--resume` needs the settings of the interrupted run**: `--seed`, `--attempts`, `--depth`, `--findings`, `--timeout`, `--memory-mb`, `--reuse` and the programs file. It refuses otherwise, and refuses a finished audit. To audit with another seed, use a new `--output` without `--resume`. The cache itself is keyed by code and world, not by seed, so a different seed may share a `--cache` directory: worlds both seeds generate come from the cache and the rest run normally. Files are removed as soon as results are saved (a program's runs when its result is saved, the gold runs when the task is done, `.resume` when the report is written), so a completed audit leaves nothing to reuse.
- Programs that ended with an environment problem (`BASELINE_RUN`, `INTERNAL_ERROR`) are not kept, so a resumed audit tries them again. `check` has no wall-time limit.
- For long audits, set the environment variable `PYTHONHASHSEED=0` in the shell that runs `isitright data check`, so that a restarted process generates worlds in the same order (`export PYTHONHASHSEED=0` in bash, `$env:PYTHONHASHSEED = "0"` in PowerShell). Python reads it at startup, so it cannot be set from a config file, and isitright does not read `.env` files. The programs under audit always run with it set to 0 in their own process; this is about the audit process. If the order ever differed, the cache would only miss.

## Agent adapters

`DataAgent.solve(question, directory)` returns the code the agent executed, its answer and its usage. `PandasAIAgent` and `SmolagentsAgent` implement it behind that one method and import their framework only when they run. PandasAI 3 pins `pandas<3` and Python 3.11 or older, so run it in its own environment. Its recorded program starts with a short prelude that defines `execute_sql_query` over DuckDB, so the program replays without PandasAI. A hosted code-execution tool is not supported.

## What a result means

A frozen finding: this program, on this world, in this host, gives an answer the gold program does not. A live finding: the agent itself, run on this world, gave an answer the gold program does not, in the counted number of runs. A statistical claim about a rate needs the sequential test to cross its boundary; below that the report gives counts. `NOT_FOUND_WITHIN_BUDGET` says what was tried, not that the program is correct.
