"""One streaming pass over the corpus: the frozen retrieval statistics of the whole corpus.

Writes stats.json (document count, average length in tokens, document frequency of every term),
computed with the research pack's own tokenizer over title + text, so a restricted world scores
with the statistics of the full corpus.

    python corpus_stats.py --data D:/Data/browsecomp-plus --out D:/Data/bcp-work/stats.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from isitright.packs.research.retrieval import tokenize

_TITLE = re.compile(r"\A---\s*\ntitle:\s*(.*)\n", re.IGNORECASE)


def title_of(text: str, url: str) -> str:
    match = _TITLE.match(text)
    return match.group(1).strip() if match else url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    df: Counter[str] = Counter()
    total = count = 0
    for file in sorted((args.data / "corpus").glob("*.parquet")):
        parquet = pq.ParquetFile(file)
        for batch in parquet.iter_batches(batch_size=512, columns=["docid", "text", "url"]):
            for row in batch.to_pylist():
                tokens = tokenize(f"{title_of(row['text'], row['url'])} {row['text']}")
                df.update(set(tokens))
                total += len(tokens)
                count += 1
        print(file.name, count, flush=True)
    args.out.write_text(
        json.dumps({"n": count, "avgdl": total / count, "df": dict(df)}), encoding="utf-8"
    )
    print({"n": count, "avgdl": total / count, "terms": len(df)})


if __name__ == "__main__":
    main()
