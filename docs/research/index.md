# Research agents

!!! warning "Experimental"
    The research pack is new in 0.8. Everything it reports about stand-in agents describes the
    stand-ins and the constructed corpus. No result in this documentation comes from a real research
    agent.

The research pack audits agents that answer a question by searching a corpus and writing a report:
a final answer and claims, each with citations (a document id and a quote). The world is a frozen
corpus behind two read-only tools. The pack plants, removes, edits, supersedes and retracts
documents in that corpus, asks what the right report is in the changed world, and returns each
disagreement as a minimized, replayable counterexample.

## What it claims and what it does not

- It claims that a given report and a given corpus disagree with an expected behavior that the
  pack computed from the corpus, and shows the documents involved.
- It does not claim which of the agent, the retriever or the corpus is at fault. Attribution stays
  `UNDETERMINED`; the report carries a classification proposed by the tool's author, labeled as a
  proposal.
- It does not claim that "no finding" means the agent is right. `NOT_FOUND_WITHIN_BUDGET` says what
  was tried.
- It does not claim a flip rate here is comparable with any published figure (see
  [DRNoise](#relation-to-drnoise)).
- It runs no model. A judge may be written behind an interface, but none is run, so support of a
  claim by its cited document (level L2) is never judged.

## The corpus and the document model

A corpus is a set of documents. Each is an entity in a `documents` collection of the core state,
with a stable `id`, typed metadata and an opaque `text`:

| Field | Meaning |
|---|---|
| `id` | Unique, stable. What `search` returns and `open` takes. |
| `title`, `source`, `authority` | Shown by the tools (title, source); authority (0 to 3) is declared, not shown. |
| `date` | An ISO date. Needed to make a newer edition. |
| `supersedes`, `duplicate_of` | References to other documents. A dangling reference is allowed. |
| `retracted` | True when the source was retracted; its text must say so. |
| `provenance` | Set by a mutator on a document it adds or changes: kind, source document, span, replaced and new value. Hidden from the agent. |

A corpus is loaded from a JSONL file (one document per line), or from a directory holding
`corpus.jsonl`, or `.txt` and `.md` files with an optional `metadata.jsonl`.

The text is never parsed by the core. Mutators that edit it declare a span: the sentence the
baseline run cited and the value inside it.

### Validity

| Tier | What it means here |
|---|---|
| `STRUCTURAL` | Ids unique, metadata types right, references of the declared kinds. |
| `DOMAIN_VALIDATED` | A superseding document is not older than what it supersedes; no reference cycles; nothing dated after the corpus cutoff; a retracted document says so; authority is 0 to 3. |
| `OBSERVABLE` | Per world, from retrieval: a document the mutation added or changed is returned by at least one query the agent (or the baseline trace, replayed) issued. Otherwise the change is `UNOBSERVABLE`: a corpus or retrieval finding, not an agent finding. |

A planted fact that contradicts another document is valid: corpora contradict themselves.
Domain validation means the rules supplied held, not that the planted text is plausible.

## Frozen retrieval, and why

`search(query, k)` ranks with BM25 (k1 = 1.2, b = 0.75, lowercase word tokens, no stemming). The
document frequencies, the document count and the average length are computed once from the
original corpus and stay fixed when a world mutates. A mutation then changes only the ranks it
intends, and a minimized corpus keeps the ranks of the documents it kept. Ties break by document
id. A planted document is scored with the frozen statistics.

Consequences, stated so they are not a surprise: a term that occurs only in a planted document has
document frequency zero and so the highest weight, which a re-indexed corpus would dampen; and a
short planted summary outranks a long document with the same term counts, because BM25 favors
short documents. Real systems re-index and often use dense retrieval. Findings describe this
retriever.

## The tools

Only two:

- `search(query, k)` returns ids, titles and snippets (the sentence closest to the query).
- `open(id)` returns the document: id, title, source, date, text.

Anything else is an error: an unknown tool name, an extra argument, `k` outside 1 to 20, an id that
does not exist. The tools reach nothing outside the corpus: no network, no file system. They are
served in process (stand-ins, frozen replay) or over MCP stdio
(`python -m isitright.packs.research.serve`, needs the `mcp` extra) for an agent command.

Fidelity is `SIMULATED`: a deterministic BM25 stands in for the retrieval stack the agent would
use. A real agent still runs for real, but the pack cannot stop an agent process that has its own
network access from using it. Run real agents in a container with no egress except to their model
provider.

## Mutators

Each is a family over documents with a declared span. All use templates; no model writes text.

| Family | Example (corpus fact: "The Halvorsen Bridge was completed in 1962.") | Expected behavior (oracle) |
|---|---|---|
| `plant` | A short summary of the cited document that says 1965. | Keep 1962, or state the conflict (constructive). |
| `contradict` | A copy of the cited document edited to say 1965, in both tie orders (the copy ranks before or after the original on an exact score tie). | Keep or state the conflict (constructive). |
| `supersede` | A newer edition dated 30 days later that says 1965 and says it supersedes the earlier one. | Use 1965, or state the newer source or the conflict (constructive; a control). |
| `retract` | The cited document is marked retracted and a notice goes first. | Abstain, or state the source is retracted (constructive; a control). |
| `remove` | Delete a cited or opened document, or a supersede copy a path added. | Abstain or state the source is gone, when no other live document states the fact (constructive). |
| `duplicate` | The cited document syndicated under another id and title. | The answer does not change (relational). |
| `out_of_scope` | A recent digest that mentions the question's terms and states no fact. | The answer does not change (relational). |
| `reorder` | `search` returns its results in reverse order. | The answer does not change (relational). |
| `snippets` | `search` returns empty snippets. | The answer does not change (relational). |

Compositions to depth two come from the core search (for example plant, then remove the original).
Where the expected answer is not defined (the original is gone and a planted document is the only
source), the oracle says `CANNOT_JUDGE`.

Listed for later: tie between equal-authority sources as its own family, a document at the
retrieval cutoff `k`, date and number representation, units, timing.

## Oracles, citations and what "flipped" means

- **Constructive.** A reference procedure over the world computes the expected behavior from the
  documents a mutation added or changed. A world where the expected answer differs from the
  baseline's is a **control**; one where it stays is a **trap**. Without a reached control a
  scenario is `NOT_DISCRIMINATING`: a refusing agent passes every trap.
- **Relational.** The normalized answer must equal the baseline's.
- **Invariant.** Citations: L0 the cited id exists; L1 the quote occurs in the cited document
  (whitespace and case normalized; an empty quote is not a match); L2 (support) is not judged. The
  report says the level reached.
- **Normalization.** `string`: case-folded, punctuation and articles removed. `number`: the first
  number, separators removed. `date`: ISO. An answer that cannot be read as the declared kind is
  `CANNOT_JUDGE`. An abstention is a declared set of phrases.
- **Three outcomes a flip count conflates.** `FOLLOWED`: the agent was shown the added document
  and its answer or citation follows it. `NOT_RETRIEVED`: no result it saw showed it. `REJECTED`:
  it was shown the document and did not follow it. Only `FOLLOWED` can be a counterexample for a
  plant or a contradiction.
- **Flags.** "The report states the conflict" uses the agent's own `flags` when present and a
  keyword rule otherwise; the report says which. Cited ids are removed from the text before the
  rule is applied.

## Subjects

| Subject | What runs | What it can answer |
|---|---|---|
| Stand-in agent (`--stand-in`) | A built-in program written by Claude. | Tests and demonstrations. Not a real agent. |
| Agent as code (`--agent module:attr --trust-code`) | An object with `run(tools, task, seed)`. | An in-process agent. |
| Agent command (`--agent-command ... --trust-code`) | Any program that can use an MCP server; it writes `report.json`. | A real agent, run by you. |
| Recorded run (`--recorded-run`) | Nothing runs. The queries are re-run on the world, the cited documents re-read, the report is not regenerated. | Whether a cited source is gone or retracted, and what the agent would now be shown. Not what it would do. |

Live agents get repeated runs, counts, a baseline repeated `k` times (flakiness is reported first),
the paired sequential test of the earlier packs, noise-tolerant minimization of the mutation path,
and budgets in runs, wall time and money (money is refused for an agent that reports no cost).
`--screen` replays the baseline trace on each candidate first and runs the agent only where the
replay shows a change it could see; it ranks and skips, it never decides.

## Reading a report

`report.json` follows the common schema; the research fields are under `extensions.research`:
the subject and who wrote it, the retrieval and its fidelity, the gold answer and whether it was
checked, the baseline queries, opened documents and citation level, a per-mutator table (worlds,
answers changed, expectations not met, behaviors), the unobservable changes, and the proposed
classification. `findings-cases.md` puts, for each finding, the question, the documents, both
reports and the verdict side by side. A finding is shown on its minimized world; the confirmation
and the oracle outcome are on that same world.

A recorded run's finding says "this recorded report on this world", never "this agent".

## Costs and safety

The tools run no model and make no call. A stand-in audit of the constructed corpus takes seconds.
A real agent costs what it costs: see the runbook (`RUNBOOK-research-agents.md` in the release
notes) for estimates and hard caps. Never put credentials in a command line; use the environment.
`--trust-code` is required for any agent that runs code or a command, and agents are not
sandboxed.

## What is unsupported

Free-text answers without a deterministic check (`CANNOT_JUDGE`), support of a claim by its
document (L2), dense or hybrid retrievers (use `--agent-command` with the corpus served by your own
stack and treat the result as unsimulated), tools other than `search` and `open`, corpora larger
than memory without a restricted per-task world (see the BrowseComp-Plus example), documents
without dates for `supersede`.

## Relation to DRNoise

DRNoise (arXiv 2607.17291) adds one plausible document that states a conflicting answer to a
frozen corpus and finds large accuracy drops. The `plant` family is that intervention with a
template. The pack adds validity tiers, a constructive or relational oracle per intervention (so a
flip that is right, such as moving to a newer edition, is not counted as an error), observability
of the change, the three-way separation above, minimization to a few documents, replay and an
exportable eval case. Numbers produced here are not comparable with theirs: different corpus,
agents and planted text.

## Quick start

```bash
# a stand-in agent on the constructed corpus (offline)
isitright research check examples/research/corpus --task examples/research/task.json \
  --stand-in credulous --output out
isitright research replay out/1.replay.json
isitright research export out/report.json --output cases
```

`examples/research/` holds the corpus, the task, and `command_agent.py`, a scripted agent that
talks to the server over MCP and shows the agent-command contract.

The task file:

```json
{"id": "halvorsen-completed", "question": "When was the Halvorsen Bridge completed?",
 "answer_type": "number", "gold": "1962",
 "gold_basis": "taken from the constructed corpus by its author; not checked",
 "reader_pattern": "completed in (\\d{4})", "cutoff": "2024-12-31"}
```

`gold_basis` says whether the gold answer was checked against anything; every finding repeats it.
`reader_pattern` is read only by the stand-in agents.
