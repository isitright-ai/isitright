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
