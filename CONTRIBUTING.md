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

- Branch from `develop`, the integration branch, and keep changes focused. `main` holds releases
  only; both branches accept changes through pull requests with green CI.
- Preserve the separation between observed disagreement, state validity, and defect
  attribution.
- Do not describe bounded agreement as equivalence.
- Document user-visible behavior and known limitations.
- Confirm Ruff, strict mypy, tests, schema freshness, and package builds locally.

Fixture semantics require owner review because they define expected behavior rather
than merely exercising implementation details. That covers entity schemas, constraints, hint
declarations, oracle rules and expected results: mark a draft with a `Proposed fixture: pending
owner review` header comment and list it in the pull request.

CI (`.github/workflows/ci.yml`) runs the checks above on Ubuntu and Windows with Python 3.11, 3.12
and 3.13, and on macOS (Apple Silicon) with the versions listed in its matrix. A macOS job that is
cancelled before any step runs, with "The job was not acquired by Runner of type hosted", ran out of
GitHub's runner capacity; it is not a test failure. Rerun the failed job.

## Releasing

The version is written in one place, `src/isitright/__about__.py`. The package metadata, `isitright
--version` and the tests read it from there. The changelog has one heading per version, newest
first: `## X.Y.Z.devN - Title` while a version is developed, `## X.Y.Z - Title` once released.
`tools/release.py` changes exactly these two lines:

```console
python tools/release.py X.Y.Z --dry-run                    # print the lines it would change
python tools/release.py X.Y.Z                              # release: rename the heading
python tools/release.py X.Y.Z.dev0 --title "Next thing"    # start the next version on develop
```

It refuses (exit code 2, nothing written) a version that is not `X.Y.Z` or `X.Y.Z.devN`, one that
is not greater than the current version, one that already has a tag (`vX.Y.Z` or `X.Y.Z`), a
working tree with uncommitted changes to tracked files, a release whose top changelog heading is not
`X.Y.Z.devN`, and a new development version without `--title`.

A release, step by step:

1. **Automatic:** run the workflow **Prepare release** (Actions tab, `workflow_dispatch`) with the
   version. With `dry_run` checked (the default) it only prints the lines it would change. Without
   it, it cuts `release/X.Y.Z` from `develop`, runs `tools/release.py X.Y.Z`, commits, pushes and
   opens the pull request into `main`.
2. **You:** when CI is green, merge the release pull request.
3. **You:** run the workflow **Publish distributions** on `main` and approve the `pypi`
   environment when asked. It publishes to TestPyPI, installs from there, publishes to PyPI and
   creates the GitHub release and tag `vX.Y.Z`. It is never started automatically.
4. **Automatic:** the push to `main` starts **Sync main into develop**, which opens the pull request
   that merges `main` back into `develop` from a branch `sync/main-<commit>-into-develop` and turns
   on auto-merge. It merges itself when CI is green. If the branches conflict (only when `develop`
   changed the same lines, for example the version), merge `develop` into the sync branch, resolve,
   and push.
5. **You:** start the next version on a branch from `develop` with
   `python tools/release.py X.Y.Z.dev0 --title "..."`.

What the two automatic workflows need, once (neither is set up by the repository itself):

- **A token secret named `RELEASE_PR_TOKEN`** (Settings, Secrets and variables, Actions). Pull
  requests opened with the default `GITHUB_TOKEN` do not start CI, and both protected branches need
  green CI. Use a fine-grained personal access token limited to this repository with the
  permissions *Contents: read and write* and *Pull requests: read and write*, or a GitHub App token
  with the same. Without the secret both workflows stop with an error before changing anything; a
  dry run works without it.
- **The repository setting "Allow auto-merge"** (Settings, General, Pull Requests), for step 4.
  Without it the sync pull request is still opened, and the workflow fails with a message saying so;
  merge it by hand.

## Documentation

The site at https://docs.isitright.ai is built with [Zensical](https://zensical.org) from `docs/` and
`zensical.toml`, and deployed to GitHub Pages by `.github/workflows/docs.yml` on pushes to `main`.

```console
python -m pip install zensical==0.0.74
zensical serve          # http://localhost:8000, rebuilds on change
zensical build --clean  # writes site/
```

A new page needs an entry in the `nav` of `zensical.toml`. Keep examples runnable: every command and
code block in the quick starts and guides was run against the release the docs describe. Pages do
not state the package version (a test checks that the version string is written only in
`__about__.py`); say "new in 0.9" where a feature's age matters. Do not backfill documentation for
earlier releases.

## Layout

`src/isitright/core/` knows nothing about SQL or MCP and must not name a pack's fields or values
(a test enforces this for the families). A pack lives in `src/isitright/packs/<name>/`. The core's
extension API is public and experimental until a pack is written by someone else.
