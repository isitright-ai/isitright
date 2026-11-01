# SQL setup with an LLM

Read [Onboarding with an LLM](index.md) first for the rules. This page has three pieces: a profile
script that collects facts about your data, a prompt that drafts [domain constraints](../sql/domain-constraints.md) from them, and a
prompt that fits a schema dump to the supported subset.

[Hints](../concepts/hints.md) need no setup for SQL: the pack harvests them from your queries.

## 1. Profile your database

Domain rules should come from what your system **guarantees**, and the profile is a source of
questions about that, not of rules. This script prints a compact profile of a SQLite database:
null counts, distinct counts, min and max, and the values of low-cardinality columns.

```python
"""Print a compact profile of a SQLite database: facts to give an LLM, not rules."""
import sqlite3
import sys

path, show_values = sys.argv[1], "--no-values" not in sys.argv
con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
for table in tables:
    total = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    print(f"\n## {table} ({total} rows)")
    for _, column, ctype, notnull, _, pk in con.execute(f'PRAGMA table_info("{table}")'):
        nulls, distinct, low, high = con.execute(
            f'SELECT SUM("{column}" IS NULL), COUNT(DISTINCT "{column}"), '
            f'MIN("{column}"), MAX("{column}") FROM "{table}"').fetchone()
        line = (f"- {column} {ctype}{' PK' if pk else ''}{' NOT NULL' if notnull else ''}: "
                f"{nulls or 0} null, {distinct} distinct")
        if show_values:
            line += f", min={low!r}, max={high!r}"
            if 0 < distinct <= 10:
                values = [v for (v,) in con.execute(
                    f'SELECT DISTINCT "{column}" FROM "{table}" ORDER BY 1')]
                line += f", values={values}"
        print(line)
```

```console
python profile_db.py data/shop.sqlite > profile.txt            # with values
python profile_db.py data/shop.sqlite --no-values > profile.txt # counts only, for sensitive data
```

The script opens the database read-only. For PostgreSQL, run the equivalent aggregate queries, or
profile a copy.

## 2. Draft domain constraints

Fill in the bracketed parts and paste with the schema and the profile.

````text
I am setting up isitright to audit text-to-SQL queries against perturbed databases. I need a domain
constraints file: JSON Schema, Draft 2020-12, in YAML. It describes the database as a snapshot: one
property per table, each an array of row objects, as in this example:

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

isitright generates changed databases and rejects any that break these rules, so every rule you write
is enforced as true. A rule that is too strict hides real bugs; a rule that is too loose lets
absurd databases through.

SCHEMA (DDL):
[paste]

PROFILE OF TODAY'S DATA (facts, not rules):
[paste]

WHAT I KNOW THE SYSTEM GUARANTEES (business rules, source systems, application code):
[paste, or write "nothing beyond the DDL"]

Do three things.
1. Write the constraints file. Include a rule only if the DDL, or what I told you the system
   guarantees, supports it. Do NOT infer a rule from the profile alone: "no NULLs in this column
   today" is not "NULL is impossible". Allow null in the type unless I said the column is never null.
2. After the file, list every rule you wrote as: rule, the evidence from my text or the DDL.
3. Then list questions I should answer for the columns where the profile suggests a rule that you did
   not write (a column with no NULLs, a narrow range, a low-cardinality column that is not an enum).
   For each, say what bug class a wrong rule would hide.

Output the YAML in one code block, then the two lists. Use only tables and columns that appear in
the schema.
````

**Review.** For each rule, ask: does something in the system *enforce* this? If you cannot point to
it, delete the rule. Then run:

```console
isitright sql check --database data/shop.sqlite --reference ref.sql --candidate cand.sql \
  --constraints rules.yaml
```

Open the report and check "Rules generation could not use" (rules that are check-only) and
`search.rejected` (how many candidates the rules threw away). A rule that rejects most candidates is
either very tight or contradicts the schema.

## 3. Fit a schema to the supported subset

PostgreSQL and DuckDB take DDL only, and only the [supported subset](../sql/supported-sql.md). A
production dump usually has things outside it. This prompt trims a copy for you to review.

````text
I need to run a tool that accepts a restricted subset of PostgreSQL DDL. Rewrite my schema into that
subset and tell me exactly what you changed.

SUPPORTED:
- unqualified table names (no schema prefix);
- primary keys: single-column SMALLINT, INTEGER, BIGINT, TEXT, VARCHAR(n) or UUID, inline or table-level;
- foreign keys: simple, single-column, and the column type must equal the referenced key's type;
- column types: the key types plus NUMERIC/DECIMAL(p,s), REAL, DOUBLE PRECISION, BOOLEAN, DATE,
  TIMESTAMP, TIMESTAMPTZ; VARCHAR(n) with n from 1 to 10000;
- single-column UNIQUE; literal defaults; GENERATED BY DEFAULT AS IDENTITY; CHECK constraints.

NOT SUPPORTED: composite primary keys, composite or cyclic foreign keys, foreign key actions
(ON DELETE ...), non-literal defaults (now(), nextval, expressions), GENERATED ALWAYS identity,
other type parameters, views, triggers, enums, arrays, jsonb, and anything else not listed above.

MY QUERIES (only these tables and columns matter):
[paste the reference and candidate SQL, or the tables they use]

MY SCHEMA:
[paste pg_dump --schema-only output]

Rules:
- Keep only the tables the queries use, plus tables they reference through foreign keys.
- Replace an unsupported type with the closest supported one and list it. Drop a column the queries
  do not use rather than guessing its type.
- For a composite key, say so and stop on that table instead of inventing a surrogate key.
- Output the DDL in one code block, then a list of every change with the reason. Do not add
  constraints I did not have.
````

!!! warning "A trimmed schema is a different world"
    Dropping columns and tables narrows what the audit can perturb. Keep the trimmed DDL with the
    report and say so when you share a finding.

## 4. Check the result

```console
isitright sql check --engine postgres --schema trimmed.sql --reference ref.sql --candidate cand.sql
```

If the run rejects the DDL, the error names the construct. Feed that line back to the model, or edit
the DDL by hand.

Next: [Audit a suite](../sql/audit-a-suite.md).
