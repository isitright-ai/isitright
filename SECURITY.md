# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's **Security →
Report a vulnerability** workflow for `isitright-ai/isitright`. Do not open a public
issue before maintainers have had an opportunity to investigate.

Include the affected version, a minimal reproduction, expected impact, and any known
workarounds. Maintainers will acknowledge the report, assess severity, and coordinate
disclosure and a patched release.

## Security boundary

`isitright` treats SQL and database files as untrusted inputs, but programmatic
validator callbacks as trusted local code. It does not load Python callbacks from
constraint documents. Analysis uses disposable in-memory SQLite copies with parser,
query-only, authorizer, deadline, and result-size controls. These controls reduce
risk. Replay separately authorizes only the DDL and inserts needed by generated
fixtures, denies database attachment and extension loading, and bounds fixture/query
execution time and query result rows. These controls are not a general sandbox for
hostile native SQLite extensions or arbitrary SQLite programs.

The v0.2 PostgreSQL path accepts a deliberately restricted parser-validated SQL
and schema subset. It starts a disposable local PostgreSQL process with loopback-only
listening and temporary data. The bundled server uses trust authentication for local
connections while running; other processes on the same machine can connect during
that time. Queries run in read-only transactions with statement deadlines and bounded
result fetching. DuckDB emulation disables external access and applies deadlines and
result caps. Replay validates and reconstructs generated rows instead of executing
arbitrary report SQL. These controls are not a general OS sandbox; use a separate
machine or stronger isolation for hostile inputs. JSON Schema remote references are
rejected in this path. No production database or credentials are used.

## Agents, data and research packs, and reports

These parts are not covered by the controls above.

- **`isitright agents run`** starts your agent command as your user, in the directory isitright was
  launched from, with your full environment variables, network and file access. It is not a sandbox.
  A tool result that the agent reads can come from a perturbed world, so text injected into it can
  steer an agent that holds real credentials. Run the agent in a container or a separate account
  with only the keys it needs. `agent.log` in each run directory holds the agent's output and can
  contain secrets; do not publish it unchecked.
- **The data pack** runs recorded programs and the gold program in a separate, limited child
  process. That is not a security boundary. Use a container for programs you do not trust.
- **Scenarios, mutators, oracles and validators** are Python and run only with `--trust-code`.
- **A report is an input.** `data export`, `data replay`, `research export` and `agents export` and
  `replay` read names and paths from `report.json`. From 0.8.1 every such path must stay inside the
  report's directory (or the output directory); a path that is absolute, names a drive, contains `..`
  or leaves the directory through a link is refused with exit code 2. 0.6.0 to 0.8.0 wrote files to
  paths taken from the report in `data export`: do not run it on a report you did not write
  with those versions. Replaying a report with `--trust-code` runs code it names; only replay reports
  you trust.
