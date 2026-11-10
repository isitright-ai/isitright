# Research pack quick start (offline)

An invented corpus of 24 documents (`corpus/corpus.jsonl`), one task (`task.json`: "When was the
Halvorsen Bridge completed?", gold 1962) and a scripted agent that talks to the corpus tools over
MCP (`command_agent.py`). The corpus, task and stand-in agents are proposed fixtures written by
Claude (see `PROPOSED_FIXTURE.txt`); no result from them is about a real research agent.

```bash
# audit a stand-in agent: the credulous one follows whatever ranks first
isitright research check examples/research/corpus --task examples/research/task.json \
  --stand-in credulous --depth 1 --output out

# findings: out/report.json, out/findings-cases.md, out/N.replay.json, out/N.eval-case.json
isitright research replay out/1.replay.json
isitright research export out/report.json --output cases

# the careful stand-in is not flagged, and its controls discriminate
isitright research check examples/research/corpus --task examples/research/task.json \
  --stand-in careful --output out-careful

# an agent command over the real MCP server (needs the mcp extra; about a minute)
isitright research check examples/research/corpus --task examples/research/task.json \
  --agent-command "python examples/research/command_agent.py --task examples/research/task.json {mcp_config} {run_dir}" \
  --trust-code --depth 1 --attempts 6 --no-minimize --output out-command
```

`docs/research/index.md` explains the mutators, the oracles and how to read a report.
`browsecomp_plus/` holds the scripts of a demo on published runs of the BrowseComp-Plus benchmark.
