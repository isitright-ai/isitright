"""A command-line analysis program, the stand-in for a package such as SPSS.

    python analyze.py --input data.csv --output out.csv --group region --value amount

Writes one row per group with the mean of ``--value``. It skips empty cells, like a statistics
package that treats a blank as missing. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--integer-mean", action="store_true", help="a defect: truncate the mean")
    args = parser.parse_args()
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    with open(args.input, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row[args.value] == "":
                continue
            sums[row[args.group]] += float(row[args.value])
            counts[row[args.group]] += 1
    with open(args.output, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([args.group, "mean", "n"])
        for key in sorted(sums):
            mean = sums[key] / counts[key]
            writer.writerow([key, int(mean) if args.integer_mean else mean, counts[key]])


if __name__ == "__main__":
    main()
