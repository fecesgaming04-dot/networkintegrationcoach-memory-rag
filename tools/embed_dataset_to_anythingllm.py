#!/usr/bin/env python3
"""Embed the synthetic network guide dataset into AnythingLLM Desktop.

The dataset intentionally contains many semantically repeated examples with
small scenario/path/IP variations. This script embeds normalized examples once
through Ollama, then writes one LanceDB vector row for every JSONL record with
the exact record text preserved in metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import lancedb


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "data" / "network_guide_2M.jsonl"
DEFAULT_STORAGE = Path(os.environ.get("APPDATA", "")) / "anythingllm-desktop" / "storage"
DEFAULT_WORKSPACE = "networkintegrationcoach"
DEFAULT_MODEL = "nomic-embed-text:latest"
DOC_ID = "network_guide_2M_jsonl"

CANONICAL_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Scenario \d+"), "Scenario N"),
    (re.compile(r"batch_\d+"), "batch_N"),
    (re.compile(r"192\.168\.\d+\.\d+"), "192.168.X.Y"),
    (re.compile(r"\b\d+\.\d+\.\d+\.\d+\b"), "X.X.X.X"),
    (re.compile(r"\b\d{2,5}\b"), "N"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def level_from_instruction(instruction: str) -> str:
    match = re.search(r"\[level:([^\]]+)\]", instruction)
    return match.group(1) if match else "unknown"


def record_text(row: dict) -> str:
    return (
        f"Instruction: {row['instruction']}\n"
        f"Answer: {row['output']}\n"
        f"Topic: {row['topic']}"
    )


def canonicalize(text: str) -> str:
    for pattern, replacement in CANONICAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def stable_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def iter_jsonl(path: Path) -> Iterable[Tuple[int, dict]]:
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if line.strip():
                yield index, json.loads(line)


def ollama_embed(base_url: str, model: str, texts: List[str], timeout: int) -> List[List[float]]:
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama embedding HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Ollama embedding request failed: {exc}") from exc

    embeddings = body.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError(
            f"Ollama returned {len(embeddings) if isinstance(embeddings, list) else 0} "
            f"embeddings for {len(texts)} inputs"
        )
    return embeddings


def load_progress(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_progress(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def collect_unique_canonicals(dataset: Path, progress: Path, report_every: int) -> Dict[str, str]:
    start = time.time()
    unique: Dict[str, str] = {}
    total = 0
    for total, (_, row) in enumerate(iter_jsonl(dataset), start=1):
        canonical = canonicalize(record_text(row))
        unique.setdefault(stable_hash(canonical), canonical)
        if total % report_every == 0:
            elapsed = max(time.time() - start, 0.001)
            print(
                f"[scan] rows={total:,} unique={len(unique):,} "
                f"rate={total / elapsed:,.0f}/s",
                flush=True,
            )
            save_progress(
                progress,
                {
                    "phase": "scan",
                    "rows_scanned": total,
                    "unique_canonical": len(unique),
                    "updated_at": utc_now(),
                },
            )
    print(f"[scan] complete rows={total:,} unique={len(unique):,}", flush=True)
    return unique


def build_embedding_cache(
    unique: Dict[str, str],
    cache_path: Path,
    base_url: str,
    model: str,
    batch_size: int,
    timeout: int,
    progress: Path,
) -> Dict[str, List[float]]:
    cache: Dict[str, List[float]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"[cache] loaded cached embeddings={len(cache):,}", flush=True)

    missing = [(key, text) for key, text in unique.items() if key not in cache]
    if not missing:
        return cache

    start = time.time()
    for offset in range(0, len(missing), batch_size):
        batch = missing[offset : offset + batch_size]
        keys = [key for key, _ in batch]
        texts = [text for _, text in batch]
        vectors = ollama_embed(base_url, model, texts, timeout)
        for key, vector in zip(keys, vectors):
            cache[key] = vector
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

        done = min(offset + len(batch), len(missing))
        elapsed = max(time.time() - start, 0.001)
        print(
            f"[embed-cache] embedded={done:,}/{len(missing):,} "
            f"rate={done / elapsed:,.1f}/s",
            flush=True,
        )
        save_progress(
            progress,
            {
                "phase": "embed-cache",
                "cached_embeddings": len(cache),
                "unique_canonical": len(unique),
                "updated_at": utc_now(),
            },
        )
    return cache


def workspace_id(db_path: Path, slug: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,)).fetchone()
    if not row:
        raise RuntimeError(f"AnythingLLM workspace slug not found in SQLite DB: {slug}")
    return int(row[0])


def prepare_workspace_document(db_path: Path, workspace_id_value: int, dataset: Path, reset: bool) -> None:
    metadata = {
        "title": "network_guide_2M.jsonl",
        "docAuthor": "Codex synthetic dataset generator",
        "description": "Synthetic phone-to-laptop networking coaching dataset.",
        "docSource": "local-jsonl",
        "chunkSource": f"localfile://{dataset}",
        "published": int(time.time() * 1000),
        "wordCount": None,
    }
    now = utc_now()
    with sqlite3.connect(db_path) as conn:
        if reset:
            conn.execute("DELETE FROM document_vectors WHERE docId = ?", (DOC_ID,))
        conn.execute(
            """
            INSERT INTO workspace_documents
              (docId, filename, docpath, workspaceId, metadata, pinned, watched, createdAt, lastUpdatedAt)
            VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
            ON CONFLICT(docId) DO UPDATE SET
              filename=excluded.filename,
              docpath=excluded.docpath,
              workspaceId=excluded.workspaceId,
              metadata=excluded.metadata,
              lastUpdatedAt=excluded.lastUpdatedAt
            """,
            (
                DOC_ID,
                dataset.name,
                str(dataset),
                workspace_id_value,
                json.dumps(metadata),
                now,
                now,
            ),
        )
        conn.commit()


def open_lance_table(lancedb_dir: Path, table_name: str, reset: bool):
    lancedb_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(lancedb_dir))
    if reset and table_name in db.table_names():
        db.drop_table(table_name)
    return db, db.open_table(table_name) if table_name in db.table_names() else None


def insert_rows(
    dataset: Path,
    lancedb_dir: Path,
    sqlite_db: Path,
    table_name: str,
    cache: Dict[str, List[float]],
    progress: Path,
    insert_batch: int,
    report_every: int,
    sleep_seconds: float,
    limit: int | None,
    reset: bool,
    write_document_vectors: bool,
) -> int:
    db, table = open_lance_table(lancedb_dir, table_name, reset)
    prepare_workspace_document(sqlite_db, workspace_id(sqlite_db, table_name), dataset, reset)

    completed = 0 if reset else int(load_progress(progress).get("rows_inserted", 0) or 0)
    pending_rows: List[dict] = []
    pending_doc_vectors: List[Tuple[str, str, str, str]] = []
    start = time.time()
    now = utc_now()

    sqlite_conn = sqlite3.connect(sqlite_db)
    try:
        for index, row in iter_jsonl(dataset):
            if limit is not None and index >= limit:
                break
            if index < completed:
                continue

            text = record_text(row)
            key = stable_hash(canonicalize(text))
            vector = cache.get(key)
            if vector is None:
                raise RuntimeError(f"Missing embedding cache entry for record {index} hash {key}")

            vector_id = f"network-guide-{index:07d}"
            pending_rows.append(
                {
                    "id": vector_id,
                    "vector": vector,
                    "text": text,
                    "topic": row["topic"],
                    "level": level_from_instruction(row["instruction"]),
                    "record_index": index,
                    "docId": DOC_ID,
                    "docSource": "network_guide_2M.jsonl",
                    "chunkSource": str(dataset),
                }
            )
            if write_document_vectors:
                pending_doc_vectors.append((DOC_ID, vector_id, now, now))

            if len(pending_rows) >= insert_batch:
                if table is None:
                    table = db.create_table(table_name, pending_rows)
                else:
                    table.add(pending_rows)
                if write_document_vectors:
                    sqlite_conn.executemany(
                        """
                        INSERT INTO document_vectors (docId, vectorId, createdAt, lastUpdatedAt)
                        VALUES (?, ?, ?, ?)
                        """,
                        pending_doc_vectors,
                    )
                    sqlite_conn.commit()
                pending_rows.clear()
                pending_doc_vectors.clear()

                completed = index + 1
                if completed % report_every == 0:
                    elapsed = max(time.time() - start, 0.001)
                    print(
                        f"[insert] rows={completed:,} rate={completed / elapsed:,.0f}/s",
                        flush=True,
                    )
                    save_progress(
                        progress,
                        {
                            "phase": "insert",
                            "rows_inserted": completed,
                            "table": table_name,
                            "updated_at": utc_now(),
                        },
                    )
                    if sleep_seconds:
                        time.sleep(sleep_seconds)

        if pending_rows:
            if table is None:
                table = db.create_table(table_name, pending_rows)
            else:
                table.add(pending_rows)
            if write_document_vectors:
                sqlite_conn.executemany(
                    """
                    INSERT INTO document_vectors (docId, vectorId, createdAt, lastUpdatedAt)
                    VALUES (?, ?, ?, ?)
                    """,
                    pending_doc_vectors,
                )
                sqlite_conn.commit()
            completed += len(pending_rows)

        if table is None:
            raise RuntimeError("No rows were inserted into LanceDB")
        save_progress(
            progress,
            {
                "phase": "complete",
                "rows_inserted": completed,
                "lancedb_count": table.count_rows(),
                "table": table_name,
                "updated_at": utc_now(),
            },
        )
        print(f"[insert] complete rows={completed:,} lancedb_count={table.count_rows():,}", flush=True)
        return completed
    finally:
        sqlite_conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--storage", type=Path, default=DEFAULT_STORAGE)
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--embedding-model", default=DEFAULT_MODEL)
    parser.add_argument("--embed-batch", type=int, default=128)
    parser.add_argument("--insert-batch", type=int, default=2500)
    parser.add_argument("--report-every", type=int, default=25000)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--skip-document-vectors", action="store_true")
    args = parser.parse_args()

    if not args.dataset.exists():
        raise FileNotFoundError(args.dataset)
    if not args.storage.exists():
        raise FileNotFoundError(args.storage)

    progress = args.dataset.with_suffix(".anythingllm_embed_progress.json")
    cache_path = args.dataset.with_suffix(".embedding_cache.json")
    sqlite_db = args.storage / "anythingllm.db"
    lancedb_dir = args.storage / "lancedb"

    print(f"[config] dataset={args.dataset}", flush=True)
    print(f"[config] storage={args.storage}", flush=True)
    print(f"[config] workspace={args.workspace}", flush=True)
    print(f"[config] embedding_model={args.embedding_model}", flush=True)

    unique = collect_unique_canonicals(args.dataset, progress, args.report_every)
    cache = build_embedding_cache(
        unique,
        cache_path,
        args.ollama_url,
        args.embedding_model,
        args.embed_batch,
        args.timeout,
        progress,
    )
    inserted = insert_rows(
        args.dataset,
        lancedb_dir,
        sqlite_db,
        args.workspace,
        cache,
        progress,
        args.insert_batch,
        args.report_every,
        args.sleep,
        args.limit,
        args.reset,
        not args.skip_document_vectors,
    )
    print(f"[done] inserted={inserted:,}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        raise SystemExit(130)
