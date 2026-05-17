#!/usr/bin/env python
"""Convert JSONL records into smaller text files for AnythingLLM ingestion."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_chunk(out_dir: Path, index: int, lines: list[str]) -> Path:
    path = out_dir / f"network_guide_chunk_{index:05d}.txt"
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(REPO_ROOT / "data" / "network_guide_2M.jsonl"))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "data" / "anythingllm_chunks"))
    parser.add_argument("--records-per-file", type=int, default=5000)
    parser.add_argument("--sleep-seconds", type=float, default=0.1)
    args = parser.parse_args()

    src = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    progress = out_dir / "chunk_progress.json"

    if not src.exists():
        raise FileNotFoundError(src)

    written_records = 0
    chunk_index = 0
    current: list[str] = []
    started = time.time()

    with src.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            record = json.loads(line)
            current.append(
                "\n".join(
                    [
                        f"### Topic: {record['topic']}",
                        f"Instruction: {record['instruction']}",
                        "Answer:",
                        record["output"],
                    ]
                )
            )
            written_records += 1
            if written_records % args.records_per_file == 0:
                path = write_chunk(out_dir, chunk_index, current)
                chunk_index += 1
                current = []
                elapsed = max(time.time() - started, 0.001)
                progress.write_text(
                    json.dumps(
                        {
                            "records": written_records,
                            "chunks": chunk_index,
                            "last_chunk": str(path),
                            "records_per_second": round(written_records / elapsed, 1),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"chunked {written_records} records into {chunk_index} files")
                time.sleep(args.sleep_seconds)

    if current:
        path = write_chunk(out_dir, chunk_index, current)
        chunk_index += 1
        progress.write_text(
            json.dumps({"records": written_records, "chunks": chunk_index, "last_chunk": str(path)}, indent=2),
            encoding="utf-8",
        )
    print(f"complete: {written_records} records across {chunk_index} chunks in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
