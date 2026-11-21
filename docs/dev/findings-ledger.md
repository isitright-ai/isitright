# Findings ledger: the 0.8.0 reviews

The three reviews of 0.8.0 (commit `d1d2abe`) raised 67 findings. The integrated plan merged them
into the 57 below. This is a working file for the 0.9.0 and 0.10.0 packages, not part of the
published navigation.

Each package that closes a finding updates its row: the status is `open`, `reproduced`, `rejected`
(with the reason) or `fixed` (with the commit and the package). A finding is only marked `fixed`
when a test that failed on the code it was found in passes on the fix. `reproduced (plan)` means
the integrated plan reproduced it on `d1d2abe`; no package has yet written the test.

Severity is the plan's integrated rating. Reviewers are the three reviews' own IDs ("R1 C1" is
review 1, finding C1).

| ID | Finding | Severity | Module | Reviewers | Status |
| --- | --- | --- | --- | --- | --- |
| S1 | `data export` and the data report writer write to paths taken from report JSON | Critical | `packs/data/reports.py`, `core/paths.py` | R1 C1 | fixed in 0.8.1 (hotfix H1, `d98598b`); reproduced (plan) |
| S2 | The agent under test inherits the full environment, network and files | High | `packs/mcp/runner.py` | R1 M5, R2 M12, R3 H8 | open (N11) |
| S3 | `SECURITY.md` covers the SQL path only | Medium | `SECURITY.md` | R1 M5, R2 M12 | fixed in 0.8.1 (hotfix H6, `d98598b`) |
| S4 | The research agent loader changes `sys.path` and imports by file stem | Medium | `packs/research/external.py` | R2 M12 | open (N11) |
| S5 | Inline warehouse SQL is spliced by text replacement | Medium | `packs/sql/inline.py` | R3 M3 | open (N11) |
| S6 | The data host is not a sandbox; no memory cap on macOS | Medium | `packs/data/host.py` | R1 M5, R2 M12, R3 M9 | open (after 0.10.0) |
| S7 | Actions are pinned to tags; CI has no dependency audit | Low | `.github/workflows` | R2, R3 noted | open (N11) |
| T1 | Research pairs runs against a baseline that never ran | Critical | `packs/research/audit.py` | R1 C2, R2 C2, R3 C1 | fixed in N1 (see "Fixed by N1" below); reproduced (plan); stopgap in 0.8.1 (H2) |
| T2 | Data reuses three baseline outcomes as new pairs | High | `packs/data/live.py` | R1 C2, R2 M3, R3 C2 | fixed in N1 (see below); reproduced (plan); stopgap in 0.8.1 (H2) |
| T3 | Errored and unjudged runs enter pairs as non-failures | High | `core/stochastic.py` | R1 C2, R2 M3 | fixed in N1 (see below) |
| T4 | Research case-level stability pools runs from different worlds | High | `packs/research/audit.py` | R3 H4 | fixed in 0.8.1 (H2, `d98598b`): the pooled `stability` is gone; N1 adds a test that no case-level stability exists |
| T5 | One failed run makes a world a counterexample, whatever the baseline | High | `packs/mcp/audit.py` | R1 M2, R2 H1, R3 M1 | fixed in N2 (see "Fixed by N2" below); reproduced (plan) |
| T6 | No correction across worlds and no interval on any rate | Medium | `core/stochastic.py` | R1 M2, R2 H1 M3, R3 M1 | fixed in N2 (see below) |
| T7 | Data live proceeds without a passing baseline | High | `packs/data/live.py` | R3 H2 | fixed in N2 (see below) |
| T8 | A run in which nothing could be judged reports "not found" | High | `packs/mcp/audit.py`, `packs/data/live.py` | R1 H1 | fixed in N2 (see below); the research live audit is covered too |
| V1 | Any rules file, even an empty one, grants `DOMAIN_VALIDATED` | Critical | `core/constraints.py` | R2 C1 | open (N3) |
| V2 | Timers and response edits are never validated after they apply | High | `core/world.py`, `packs/mcp/runtime` | R1 C3 | open (N4) |
| V3 | MCP minimization steps carry no validity assessment | Medium | `packs/mcp/audit.py` | R1 H2 | open (N4) |
| E1 | Warehouse `VERIFIED` can refer to the unminimized world | High | `packs/sql/audit.py` | R3 H3 | open (N5) |
| E2 | The SQL minimizer accepts any disagreement and keeps the first label | Medium | `packs/sql/audit.py` | R1 H5, R2 M6 | open (N5) |
| E3 | MCP joins a minimized path to the original world's evidence | High | `packs/mcp/audit.py` | R1 H2 | open (N5) |
| E4 | Research minimization repeats one seed and keeps findings that do not reproduce | High | `packs/research/audit.py` | R1 H2, R2 H4 | partly fixed in N1 (the seed: every call has its own); the kept non-reproducing finding stays open (N5) |
| E5 | Research baseline, minimization and confirmation run outside the budget | High | `packs/research/audit.py` | R1 H3, R2 H4, R3 H1 | fixed in 0.8.1 (H3, `d98598b`); N1 moves the check into the run loop |
| E6 | MCP minimization never checks the money or time budget | Medium | `packs/mcp/audit.py` | R1 H3 | fixed in 0.8.1 (H3, `d98598b`); N1 moves the check into the run loop |
| E7 | Live-data reports name replay files that are never written | High | `packs/data/live.py`, `packs/data/cli.py` | R1 H4 | open (N6) |
| E8 | The SQL report prints a replay command that does not exist | Medium | `packs/sql/reports.py` | R2 M2 | fixed in 0.8.1 (H4, `d98598b`); reproduced (plan) |
| E9 | Reports lack versions, configuration and the seed used | Medium | `core/evidence.py` | R1 M1, R2 M1, R3 M5 M6 | open (N7); reproduced (plan) |
| E10 | Minimization attempts are counted twice | Low | `core/minimize.py` | R2 L1 | open (N7) |
| Q1 | Tied rows under `ORDER BY` are compared by position | High | `packs/sql/comparison.py` | R1 H5, R2 H2 | open (N8); reproduced (plan) |
| Q2 | Volatile SQL is accepted | High | `packs/sql/` | R1 H5 | open (N8); reproduced (plan) |
| Q3 | SQL harvests no ordering or threshold hints, so five families never run | High | `packs/sql/hints.py` | R2 H3 | open (N9); reproduced (plan) |
| Q4 | The unordered comparator recurses once per duplicate row | High | `packs/sql/comparison.py` | R3 H7 | fixed in 0.8.1 (H5, `d98598b`); reproduced (plan) |
| Q5 | The comparator is stricter than execution-accuracy graders | Medium | `packs/sql/comparison.py` | R2 M7 | open (N8) |
| Q6 | One finding per SQL case, and no coverage per case | Medium | `packs/sql/audit.py` | R2 M14 | open (N9) |
| Q7 | Invalid SQL and `INCONCLUSIVE` behave differently by engine | Low | `packs/sql/audit.py`, `cli.py` | R2 H6 L7 | open (N10) |
| C1 | A suite exits 0 when no case was audited | High | `cli.py` | R2 H6 | open (N10); reproduced (plan) |
| C2 | The data pack has no `--fail-on`; the CI guide covers two packs | Medium | `packs/data/cli.py`, `docs/guides/ci.md` | R1 M3, R2 H6, R3 M7 | open (N10) |
| C3 | Verbs, options and policies differ across the four packs | Medium | `cli.py`, `packs/*/cli.py` | R2 M9 | open (N10) |
| C4 | Emulated findings are exempt from the fail policy without notice | Low | `cli.py` | R2 H6 | open (N10) |
| G1 | No measured detection or false-positive rate | High | `tests/` | R1 H6, R2 H5, R3 H6 | open (M1) |
| G2 | 99 files await owner review; the README says fixtures are approved | High | `tests/`, `examples/` | R1 H6, R2 H5, R3 H5 | statement fixed in 0.8.1 (H6); review open (M2) |
| G3 | Several mutation families have no assertion on their output | Medium | `tests/` | R2 M11 | open (M3) |
| G4 | BigQuery observations are outside the repository; PrestoDB is untested | Medium | `tests/test_warehouse_fidelity.py` | R1 noted, R3 M8 | open (M4) |
| X1 | A banned word in a world or invariant name stops the MCP report | Medium | `core/evidence.py` | R2 M4 | fixed in 0.8.1 (H5, `d98598b`) |
| X2 | Unnamed hints of one kind overwrite each other | Medium | `core/hints.py` | R2 M5 | open (N12) |
| X3 | The search truncates parents and errors without saying so | Low | `core/search.py` | R1 noted, R2 L5 | open (N9, N12) |
| X4 | Fixed float step, PostgreSQL tests as root, leftovers, report noise | Low | `packs/sql/`, `tests/`, `core/evidence.py` | R2 L2 to L6 | open (N9, N12) |
| P1 | No page states the limits; the first line reads wider than the build | Medium | `README.md`, `docs/` | R1 M2, R2 M13 | open (N13) |
| P2 | Five statements in the docs contradict the code | Medium | `docs/`, `README.md` | R1 L1, R2 H2 H5 M3 H6 | fixed in 0.8.1 (H6, `d98598b`) |
| P3 | No data quick start or glossary; the concept pages repeat | Low | `docs/` | R1 L1, R3 L1 | open (N13) |
| P4 | The roadmap is stale; a SpotIt+ figure and the prior art need a recheck | Low | roadmap | R2 L8 | open (N13) |
| P5 | The MCP oracle requires the reference's exact writes | Medium | `packs/mcp/oracle.py` | R3 M2 | open (N13) |
| P6 | MCP has no general check of the final message to the user | Medium | `packs/mcp/oracle.py` | R3 M4 | open (N13) |
| P7 | Research and data oracles cannot judge citation support or small-sample statistics | Medium | `packs/research/oracle.py`, `packs/data/comparison.py` | R1 M4 | open (N13) |
| P8 | No eval-framework adapter, and no JUnit or SARIF output | Medium | `cli.py` | R1 M3, R2 M8 | open (N10; adapters after 0.10.0) |
| A1 | Run loop, path conversion and loaders are copied across packs | Medium | `packs/*/audit.py` | R2 M10, R3 L2 | partly fixed in N1 (the run loop: one `SubjectRunner`); path conversion and loaders open (N14) |
| A2 | Breadth ran ahead of validation | Medium | roadmap | R2 M10, R3 M10 | open (M4, roadmap) |

## Fixed by N1

Branch `feature/0.9.0-n1-run-loop`; the commits are those on the branch before it is squashed or merged.

| ID | What N1 did | Test that failed before | Commit |
| --- | --- | --- | --- |
| T1 | Research pairs each world run with a fresh baseline run | `tests/test_run_loop_packs.py::test_research_equal_failure_rates_rarely_give_a_rate_increase` (on `d1d2abe`: 9% false claims at 30%, 39% at 50%); `::test_research_ten_against_seventy_percent_is_found` (on 0.8.1: 0 of 560 worlds, because the stopgap capped the pairs at the baseline runs) | `1ace90c`, `6516d98` |
| T2 | Data pairs each world run with a fresh baseline run | `::test_data_with_a_long_pair_limit_still_holds_the_error_rate` (on `d1d2abe`: 16% at a 20% failure rate and `--max-trials 30`); `::test_data_ten_against_seventy_percent_is_found` (on 0.8.1: 0 of 72) | `1ace90c`, `6516d98` |
| T3 | A run that errored or could not be judged forms no pair and is counted | `tests/test_run_loop.py::test_errored_and_unjudged_runs_form_no_pair_and_are_counted` (new API; the 0.8.0 data loop counted errors as passes, the 0.8.1 stopgap left them out) | `1ace90c`, `6516d98` |
| T4 | Holds from 0.8.1; a test now checks that no case-level stability exists | `tests/test_run_loop_packs.py::test_research_sequential_records_say_how_the_pairs_were_made` | `1ace90c`, `6516d98` |
| E4 (seed) | One call counter derives a distinct seed for every call, minimization included | `tests/test_run_loop_packs.py::test_research_never_reuses_a_seed_across_search_minimization_and_confirmation` (on 0.8.1: 40 distinct seeds in 93 calls) | `1ace90c`, `6516d98` |
| A1 (run loop) | `SubjectRunner` is the only code that executes a subject | `tests/test_single_run_loop.py::test_no_code_outside_the_runner_executes_a_subject` (on 0.8.1: two direct calls in `packs/research/audit.py`) | `1ace90c`, `6516d98` |

## Fixed by N2

Branch `feature/0.9.0-n2-finding-grades`; the commits are those on the branch before it is squashed or merged (last one `fb9f724` at the time of writing). Every test below failed on `develop` at `b778978` (the N1 merge) and passes on the branch; they are in `tests/test_finding_grades.py`. The 5% test also runs at 50 worlds under `pytest -m statistical`.

| ID | What N2 did | Test that failed before | Commit |
| --- | --- | --- | --- |
| T5 | A finding has an `evidence_grade`: only a paired sequential test that crossed its boundary makes it `RATE_INCREASE` and the case `COUNTEREXAMPLE_FOUND`; a failed run on a valid world is `OBSERVED_FAILURE`, shown prominently, exported and gated apart | `::test_an_agent_that_fails_five_percent_at_random_rarely_gives_a_rate_claim[small]` (on `b778978`: 9 of 12 audits of 8 worlds claimed a counterexample); `::test_one_failed_run_is_an_observed_failure_not_a_counterexample` | `fb9f724` and earlier |
| T6 | Rates print with 95% Wilson intervals (`observation`); the report states the worlds tested, that per-world decisions are uncorrected, and the claims expected by chance (`multiplicity`) | `::test_the_wilson_interval_matches_known_values`, `::test_the_report_says_how_many_worlds_were_tested_and_that_decisions_are_uncorrected` (new fields: they could not pass on `b778978`) | `fb9f724` and earlier |
| T7 | Data live stops on a baseline run that did not meet the expectation, unless `--allow-failing-baseline` | `::test_data_a_baseline_that_does_not_meet_the_expectation_stops_the_audit` (on `b778978`: the audit went on) | `fb9f724` and earlier |
| T8 | No judged run on any mutated world is `INCONCLUSIVE` (agents, data live, research live); baseline runs do not count | `::test_an_agent_that_errors_on_every_mutated_world_gives_inconclusive` (on `b778978`: `NOT_FOUND_WITHIN_BUDGET`), `::test_data_an_agent_that_errors_on_every_mutated_world_gives_inconclusive`, `::test_research_an_agent_that_errors_in_every_world_is_inconclusive` | `fb9f724` and earlier |
