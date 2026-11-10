# BrowseComp-Plus demo (frozen audit of published runs)

Scripts only. The benchmark's data is not in this repository: the benchmark asks that its data
not appear as plain text online, so decoded text stays in a local work directory.

1. `fetch.py --data DIR` downloads the files (MIT-licensed queries and corpus; the published runs have no
   stated licence, so they are for local analysis only).
2. `select_tasks.py --data DIR --out WORK/selection.json` applies the task rule (see the file).
3. `corpus_stats.py --data DIR --out WORK/stats.json` computes the frozen statistics of the whole corpus.
4. `audit_demo.py --data DIR --work WORK` audits the published BM25 + gpt-5 runs frozen.

All results describe the recorded runs and this tool's simulated BM25, not a live agent.
