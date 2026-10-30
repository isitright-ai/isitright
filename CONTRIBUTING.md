# Contributing

Thank you for helping improve `isitright`.

## Development setup

Python 3.11 or newer and `uv` are required.

```console
uv sync --locked --extra dev --extra all
uv run ruff check .
uv run mypy src
uv run python tools/export_schemas.py --check
uv run pytest
uv build
```

Tests must run offline after dependencies are installed and must not require API
keys. Add a regression test for every bug fix. Changes to report models require
running `uv run python tools/export_schemas.py` and committing the updated files in
`schemas/`.

## Pull requests

- Branch from the current `main` branch and keep changes focused.
- Preserve the separation between observed disagreement, state validity, and defect
  attribution.
- Do not describe bounded agreement as equivalence.
- Document user-visible behavior and known limitations.
- Confirm Ruff, strict mypy, tests, schema freshness, and package builds locally.

Fixture semantics require owner review because they define expected behavior rather
than merely exercising implementation details. That covers entity schemas, constraints, hint
declarations, oracle rules and expected results: mark a draft with a `Proposed fixture: pending
owner review` header comment and list it in the pull request.

## Layout

`src/isitright/core/` knows nothing about SQL or MCP and must not name a pack's fields or values
(a test enforces this for the families). A pack lives in `src/isitright/packs/<name>/`. The core's
extension API is public and experimental until a pack is written by someone else.
