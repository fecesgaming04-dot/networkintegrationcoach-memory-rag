#!/usr/bin/env python
"""Validate shape and balance of the synthetic network guide dataset."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LEVEL_RE = re.compile(r"\[level:([a-z]+)\]")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(REPO_ROOT / "data" / "network_guide_2M.jsonl"))
    parser.add_argument("--expected", type=int, default=2_000_000)
    parser.add_argument("--summary", default=str(REPO_ROOT / "data" / "network_guide_2M.summary.json"))
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        raise FileNotFoundError(path)

    required = {"instruction", "output", "topic"}
    topic_counts: Counter[str] = Counter()
    level_counts: Counter[str] = Counter()
    cell_counts: Counter[str] = Counter()
    samples = []
    total = 0

    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            total += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON on line {line_no}: {exc}") from exc
            missing = required - set(record)
            if missing:
                raise RuntimeError(f"line {line_no} missing fields: {sorted(missing)}")
            if not isinstance(record["instruction"], str) or not isinstance(record["output"], str) or not isinstance(record["topic"], str):
                raise RuntimeError(f"line {line_no} has non-string required field")
            match = LEVEL_RE.search(record["instruction"])
            if not match:
                raise RuntimeError(f"line {line_no} missing [level:...] marker in instruction")
            level = match.group(1)
            topic = record["topic"]
            topic_counts[topic] += 1
            level_counts[level] += 1
            cell_counts[f"{topic}|{level}"] += 1
            if len(samples) < 5:
                samples.append(record)

    if total != args.expected:
        raise RuntimeError(f"expected {args.expected} records, found {total}")

    summary = {
        "records": total,
        "topics": dict(sorted(topic_counts.items())),
        "levels": dict(sorted(level_counts.items())),
        "topic_level_cells": dict(sorted(cell_counts.items())),
        "samples": samples,
    }
    summary_path = Path(args.summary)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2)[:4000])
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
