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
| `supersedes`, `duplicate_of` | References to other documents. A dangling reference is allowed. `duplicate_of` means identical original content: a later retraction of the original does not invalidate an unchanged copy. |
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
  report says the level reached. Two things are reported beside the level and never change it:
  claim coverage (claims that cite nothing) and retrieval provenance (a cited document that exists
  but that the trace never shows the agent retrieving: a correct-looking citation does not show the
  agent read it).
- **Normalization.** `string`: case-folded, punctuation and articles removed. `number`: the one
  number in the answer, separators removed; an answer with two numbers ("As of 2024, ... 1962") or
  a negation before its number ("not 1962") is not an exact answer. `date`: ISO, with the same exactness
  rules (two different dates, a date and a second different year, or a date after a negation, is not an
  exact answer). An answer that
  cannot be read as the declared kind is `CANNOT_JUDGE`. An abstention is a declared set of
  phrases. Use structured answer fields; do not point this at prose.
- **A disclosure never rescues an answer.** The answer must be one the expectation recognizes (the
  baseline's, a conflicting document's, the newer edition's, or an abstention); saying the sources
  conflict makes a recognized answer acceptable and does nothing for an unrelated one.
- **Support is the cited sentence.** A document supports the cited fact if it is the cited
  document, a copy of it, or repeats its sentence. Another document that mentions the same number
  elsewhere does not.
- **Outcomes a flip count conflates.** The label respects exposure. `FOLLOWED`: the agent was shown
  the claim and its answer adopted the added document's value. `REJECTED`: it was shown the claim
  and did not adopt it. `NOT_EXPOSED`: the document appeared as an id and a title only, the claim
  was never shown, and the answer did not match it: nothing can be said about rejecting it.
  `MATCHED_WITHOUT_EXPOSURE`: the answer equals a claim it was never shown (coincidence or prior
  knowledge), which is not following it. `EXPOSURE_UNKNOWN`: the snippet was cut before the claim,
  so neither following nor rejecting can be said. The claim is the mutation's own sentence: a
  snippet that merely contains the claim's value in another sentence ("the report mentions 1965")
  does not show it. `NOT_RETRIEVED`: the document appeared in no result and
  was not opened. Underneath, each added document has its own
  observations: `appeared` (in a result or opened), `claim_exposed` (opened, or a snippet states
  the value, as against a title and an unrelated snippet), `adopted`, and `cited` (as support or as
  counter-evidence: the report does not say which). Citing a document is not adopting it. Only
  `FOLLOWED` can be a counterexample for a plant or a contradiction.
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

The stand-ins include a careful one (opens everything, newest date wins, a sentence repeated by
several documents counts once; it sees no authority because `open` does not show it), a skeptic
(answers the earliest source and cites the conflicting one as counter-evidence), an ambiguous one
(prose with two numbers: not judged) and a ghost citer (cites a real document and quote without any
tool call).

Live agents get repeated runs, counts, a baseline repeated `k` times (flakiness is reported first),
the paired sequential test of the earlier packs, noise-tolerant minimization of the mutation path,
and budgets in runs, wall time and money (money is refused for an agent that reports no cost).
`--seconds` is a cooperative budget checked between worlds, not a hard timeout on one run; use
`--timeout` for an agent command. `--screen` replays the baseline trace on each candidate first and runs the agent only where the
replay shows a change it could see; it ranks and skips, it never decides.

## Reading a report

`report.json` follows the common schema; the research fields are under `extensions.research`:
the subject and who wrote it, the retrieval and its fidelity, the gold answer and whether it was
checked, the baseline queries, opened documents and citation level, a per-mutator table (worlds,
answers changed, expectations not met, behaviors), the unobservable changes, and the proposed
classification. The flip table has, per mutator, how many worlds were run, how many answers changed,
how many expectations were not met, how many runs were not judged, and the observations behind the
three behavior labels: in how many worlds the added document appeared, its claim was exposed, the
answer adopted it and the report cited it. `findings-cases.md` puts, for each finding, the question, the documents, both
reports and the verdict side by side. A finding is shown on its minimized world; the confirmation
and the oracle outcome are on that same world.

**Runs that cannot be judged.** A run is `CANNOT_JUDGE` when its answer cannot be read as the
declared kind (prose holding two numbers, a negation) or when no right answer is defined in that
world. It is counted per mutator under `extensions.research.cannot_judge`, with up to three
examples per mutator (answers cut at 300 characters), and the headline says how many there were.
Every such run with its full answer, seed and mutation path is in `cannot-judge.jsonl` beside the
report, and `findings-cases.md` lists the examples. Not judged is not right: an agent that hedges
in prose when it notices a conflict would leave exactly the interesting worlds unjudged, so a high
count in one mutator means the audit is incomplete there. isitright does not ask the agent for a
different answer format; read the examples and decide whether your agent's answers need parsing in
its adapter.

A recorded run's finding says "this recorded report on this world", never "this agent".

## Costs and safety

The tools run no model and make no call. A stand-in audit of the constructed corpus takes seconds.
A real agent costs what it costs: a research run is many searches over a growing context, so set
`--max-runs`, `--seconds` and (for an agent that reports its cost) `--max-money` before a paid
sweep. Never put credentials in a command line; use the environment.
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

## A demo on published runs

`examples/research/browsecomp_plus/` has scripts (no benchmark data) that replay the published
BM25 + gpt-5 runs of BrowseComp-Plus frozen on mutated corpora. On 25 tasks chosen by a rule fixed
before any audit, with the world of each task restricted to the documents its run saw and the
statistics of the whole corpus (100,195 documents), the recorded reports were not regenerated, so
nothing here says what the agent would do. What it measures is exposure under this tool's BM25:
all 15 supersede worlds and all 38 contradict worlds put the added document in the results of a
recorded query; 10 of 19 plants did and 9 did not (UNOBSERVABLE); 20 of 25 out-of-scope digests were
not retrieved by any recorded query. The simulated retriever reproduced the recorded top-5 set for
95 of 492 recorded queries and the recorded first result for 270, so exposure is about this scorer,
not the benchmark's. The recorded runs carry no quotes, so their citations reach level L0 only. The fact span (the
sentence the mutations edit) is the first body sentence of a cited document that contains the run's
own answer, with no negation or correction cue; it is a heuristic, labeled as one, and does not
check that the sentence entails the answer. The report states, for a recorded run, how closely the
simulated retrieval reproduced the recorded results (`frozen_fidelity`: queries, same first result,
same result set), and says which conclusions depend on it. Findings about a cited document or quote
that the world lacks or retracts do not; exposure classes (what a changed corpus would show the
agent) and `UNOBSERVABLE` do, and each such world's basis says so with the counts. Tasks are stratified by how often the simulated
retrieval returned the recorded first result: per task, the share of its recorded queries for which
the first hit of this tool's BM25 over the task's restricted world is the first hit the benchmark's
retriever returned. Tasks are counted in fixed bins of width 0.2 (0.0-0.2 up to 0.8-1.0), with the
per-task share beside the bin and no good-or-bad label. It describes how closely the simulated
results follow what the agent actually saw, not how good either retriever is.

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
