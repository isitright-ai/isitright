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

**A final answer the agent typed is not replayable.** A code agent often computes a value in one step, reads it from the output, and then types it into `final_answer("@mean[4.61]")` in the next. The recorded program (all steps joined) then ends with a constant, and a replay on any other world would print that same constant, so every change to the data would look like a disagreement with the gold program. That is a property of how the answer was recorded, not a finding. A program whose every `final_answer(...)` call has only constant arguments (literals, constant f-strings, and sums of them) is therefore `UNSUPPORTED` with that reason. Only the live mode can test such an agent, because it runs the agent again on the new world. The check is static and direct: an answer that goes through a variable assigned a constant is not detected.

## The host and what it does not protect

Each run goes to a separate process with a fresh temporary directory, a scrubbed environment (no API keys or other variables are inherited), a wall-clock timeout and a memory limit (see below for how each platform enforces it). Nothing runs in the audit process, and nothing runs without `--trust-code` (`trust_code=True` in the API).

The Windows limit caps the memory one process may commit. The runner puts itself in the Job Object before it runs any program, because a virtualenv's `python.exe` can be a launcher (for example when uv made the environment from a Microsoft Store Python) whose child, the process that runs your code, would not be in a job the audit process creates. If the limit cannot be set the runner exits and the run is reported as an error, never as an unlimited run. A program that exceeds the limit ends with the status `memory`.

### The memory limit, by platform

`memory_limit_mb` (default 2048; `--memory-mb`) is enforced differently on each platform, and the host's description in the report says which (`memory_enforcement`):

| Platform | `memory_enforcement` | How | Exact? |
|---|---|---|---|
| Windows | `job_object` | A Job Object caps the memory the runner may commit; an allocation over the limit raises `MemoryError` | Yes |
| Linux, macOS, with `psutil` | `rss_watchdog` | The audit process reads the resident memory of the runner and its children every 10 ms (its children every tenth time) and kills the runner's process group above the limit; the runner also watches its own peak as a second line (new in 0.9) | **Approximate** |
| Linux, without `psutil` | `address_space` | `RLIMIT_AS`, which counts reserved address space, so NumPy or pandas can hit it far below their real use | Yes, but it measures the wrong thing |
| macOS, without `psutil` | `none` | macOS has no `RLIMIT_AS`: a warning says the limit is not enforced; the timeout still is | No limit |

`psutil` is part of the `data` extra, so a normal install of the data pack gets the watchdog. The watchdog's limit is **approximate**: a program can pass the limit between two readings, so the runner can use more than the limit before it is stopped. The run is reported with the status `memory` and the resident size that was read. A program stuck in one long C call is stopped by the watchdog, not by the runner's own check. Do not rely on the limit as a security boundary; for untrusted code use a container with a memory cap (`docker run --memory`), which isitright does not set up.

**Measured overshoot** (`tools/measure_memory.py`, run by CI on GitHub-hosted runners, Python 3.12, limit 300 MB, 5 runs per program, the watchdog reading the runner every 10 ms; the figure is the runner's largest resident size after it was stopped, minus the limit):

| Program | Linux (ubuntu-latest) median / max | macOS (macos-latest, Apple Silicon) median / max |
|---|---|---|
| `bytearray(1.5 GB)`, one call | 16 / 25 MB | 347 / 514 MB |
| 1.5 GB in 16 MB chunks | 21 / 27 MB | 129 / 446 MB |
| `numpy.ones` of 1.5 GB | 91 / 159 MB | 57 / 193 MB |

All fifteen runs on each platform ended with the status `memory`. These are single measurements on shared runners, one run of the script (CI, 2026-11-13), not a bound: an earlier run with a 50 ms poll that listed child processes on every reading gave medians of 660 to 870 MB on macOS and 31 to 40 MB on Linux, which is why the poll is now 10 ms and children are read every tenth time. **The limit is approximate.** On macOS it is a lower bound: a `RuntimeWarning` says so when the host starts, and the host's description in the report carries a `memory_limit_note`. Leave about 200 MB of headroom on Linux and about 600 MB on macOS above the limit you set if the host has to survive a program that allocates all at once; on Windows the Job Object refuses the allocation itself (`tests/test_data_host.py` runs the one-call and chunked programs there).

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

Two conventions here belong to the data pack, not to the core, and come from InfiAgent-DABench: answers are read as `@name[value]` pairs (a repeated block of pairs, such as one per continent, is a list of groups), and the number of decimals is read from phrases such as "rounded to two decimal places" in the question. A task from another source would use the same comparators with its own answer format.

- **Numbers**: within `abs_tol + rel_tol * |expected|`. When the question asks for N decimal places the tolerance is one unit in the last place, because the two programs may round a boundary value differently; the basis says so. On top of that the policy adds a margin of exactly **2 ulps** (units in the last place of the larger number, not of the decimals), which is floating-point representation noise: near 2,000,000 two numbers 0.01 apart differ by about 0.0100000002, so without a margin a rounding that differs by one unit at a tie (2243963.30 against 2243963.31) would count as a disagreement. (0.6 to 0.8 used a relative term of 1e-15, which is 4.5 to 9 ulps depending on the number.) **Per answer (new in 0.9):** when the clause of one named answer states its own precision, that answer uses it: "`r_value` rounded to two decimal places, and `p_value` to four" compares `p_value` with a tolerance of 0.0001 and `r_value` with 0.01 (0.6 used the fewest, 0.01, for both). A clause that names two precisions, or none, gives its answer the task's fewest. A task that states `abs_tol` in `task.yaml` applies it to every answer unless it also states `per_answer` (a mapping from the normalized answer name to its decimals) and `ulps`. When the question names no number of decimals the tolerance is floating-point noise only (1e-9, absolute and relative), so an answer that was rounded and a reference that was not disagree. This is deliberately loose where decimals are stated: a difference smaller than the tolerance is not found.
- **Text**: equal after trimming and case folding (`text: none` for exact). One pair of quotes around a single value (`'Kuwait'`) is ignored.
- **Named answers**: names are compared after normalization, values by their kind. A bare value stands for a task with one named answer. A list equals the same items in a comma-separated string, with or without brackets and quotes (`['a', 'b']`), and a list of names has no order.
- **Groups**: when the first answer name comes round again (`@continent_name[...]` `@r[...]` ... repeated per continent) the answer is a list of groups. Groups are matched by the value of their first answer, so their order does not matter. A reference program returns the same shape as a list of dicts.
- **Frames**: columns, dtype kind, values; the index is ignored unless the policy says `strict`.
- **An undefined reference answer** (the mean of an empty column, a division by zero that makes a correlation NaN) is not compared: the world is inconclusive in the frozen audit and is not run on the agent in live mode.

## Hints

Hints come from the program (`ast`), the schema and the question text, never from gold answers. A program yields `scope` (the files it reads), `column`, `literal` and `threshold` hints (constants compared with a column, with the side and inclusivity), and `ordering` hints (sort keys, `nlargest`, `idxmax`, `drop_duplicates`). The question text adds `column` hints with provenance `harvested:question`. Declared hints in `hints.yaml` use the core format. Model-proposed hints stay labeled `proposed` and never raise a validity tier.

## Constraints

Domain rules use the core constraint language (`range`, `one_of`, `not_null`, `unique`, and since 0.9 `row_count`), declared in `constraints.yaml`. `{kind: row_count, collection: orders, min: 3}` bounds a table's size (`min`, `max` or both); every generated world and every minimization step is checked against it, so a counterexample never has fewer rows than you declared. With no rules a finding is `STRUCTURAL` only. A pandera schema can be imported (extra `data-schema`):

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
- `audit` is the live audit. `--agent module:callable` builds a `DataAgent` (see `isitright.packs.data.adapters`) in a separate process that receives only the variables named by `--pass-env`. `--attempts` sets the attempts of both the frozen check that finds the minimized world and the live world search. `--max-runs`, `--max-money` and `--max-seconds` are budgets; `--max-worlds` is a safety rail; `--stratum-patience`, `--run-patience` and `--run-patience-share` are the stopping rules (the run rule stops after the larger of `--run-patience` and that share of the worlds ranked). A world the agent was not run on is listed as `NOT_RUN` with the reason. A money budget needs the agent to report its cost. `--env-file FILE` reads the `--pass-env` variables (for example an API key) from a dotenv-style file: only the named variables are used, a variable already in the environment wins, no value is printed, and the command refuses to start if a named variable is still not set. Keep that file out of version control and out of synced folders.
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

`SmolagentsAgent` details that came from running it against a real model:

- **Failed steps.** An agent often runs a step that raises an error, reads it and recovers in a later step; the agent's executor keeps what the failed step defined before the error. The steps are joined into one program with a failed step wrapped in `try / except Exception: pass`, so the replay carries on the same way. Without that, the replay stops at the first failed step and the recording does not run on the original data.
- **Imports.** smolagents checks an import part by part, so `"scipy"` alone rejects `scipy.stats` and `"numpy"` alone rejects `numpy.random`. The default list therefore has a `"<name>.*"` entry for `pandas`, `numpy` and `scipy`. The environment that runs the agent needs those libraries installed.
- **`stop` parameter.** Newer OpenAI models reject the `stop` parameter that `CodeAgent` sends, so the adapter tells smolagents to drop it for the OpenAI model it builds.
- **Cost.** With `usd_per_million_tokens=(input, output)` the run reports its cost, which `--max-money` needs. `examples/data/dabench/capture.py` takes `--max-money` too and writes its recordings after every run.

## What a result means

A frozen finding: this program, on this world, in this host, gives an answer the gold program does not. A live finding: the agent itself, run on this world, gave an answer the gold program does not, in the counted number of runs. A statistical claim about a rate needs the sequential test to cross its boundary; below that the report gives counts. `NOT_FOUND_WITHIN_BUDGET` says what was tried, not that the program is correct.

Two cautions for reading a finding:

- **Small minimized worlds.** Minimization keeps the fewest rows that keep the disagreement. For a statistic (a correlation, a standard deviation) that can leave two or three rows, where the reference answer is degenerate (the correlation of two points is always 1) and an agent that answers "undefined" is not obviously wrong. Look at the data before reading such a finding as a defect, or declare `row_count` with a `min` (for a correlation, three rows) so that minimization cannot shrink the table below it.
- **Validity tier.** With no declared rules a finding is `STRUCTURAL` only. A stray non-breaking space in a numeric text column is a world the data could contain, but nothing in the task says so. Declare the rules the data follows (`constraints.yaml`) before treating a finding as strong evidence.

A live finding is also a count over a few runs of a stochastic agent: the same minimized world gave 3 of 3 matching runs in one live audit and 2 of 3 in another.
