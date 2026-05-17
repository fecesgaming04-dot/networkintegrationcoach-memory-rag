#!/usr/bin/env python3
"""OpenAI-compatible semantic memory proxy for NetworkIntegrationCoach.

The proxy keeps AnythingLLM as the RAG/UI layer and Bonsai llama-server as the
LLM layer. It adds a small semantic memory tank in a separate LanceDB table:
retrieve relevant distilled prior turns before each answer, then store a compact
memory record after each answer and erase the active Bonsai slot.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import lancedb
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("MEMORY_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMORY_PROXY_PORT", "8081"))
BONSAI_BASE = os.environ.get("BONSAI_OPENAI_BASE", "http://127.0.0.1:8080/v1").rstrip("/")
BONSAI_SERVER = BONSAI_BASE[:-3] if BONSAI_BASE.endswith("/v1") else BONSAI_BASE
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_PATH", "http://127.0.0.1:11434").rstrip("/")
EMBEDDING_MODEL = os.environ.get("MEMORY_EMBEDDING_MODEL", "nomic-embed-text:latest")
STORAGE_DIR = Path(
    os.environ.get(
        "ANYTHINGLLM_STORAGE_DIR",
        str(Path(os.environ.get("APPDATA", "")) / "anythingllm-desktop" / "storage"),
    )
)
LANCEDB_DIR = Path(os.environ.get("MEMORY_LANCEDB_DIR", str(STORAGE_DIR / "lancedb")))
MEMORY_TABLE = os.environ.get("MEMORY_TABLE", "networkintegrationcoach_memory")
LOG_PATH = Path(
    os.environ.get(
        "MEMORY_PROXY_LOG",
        str(REPO_ROOT / "logs" / "memory_proxy.log"),
    )
)

MEMORY_TOP_K = int(os.environ.get("MEMORY_TOP_K", "4"))
MEMORY_BLOCK_MAX_CHARS = int(os.environ.get("MEMORY_BLOCK_MAX_CHARS", "2400"))
MEMORY_RECORD_MAX_CHARS = int(os.environ.get("MEMORY_RECORD_MAX_CHARS", "6000"))
REQUEST_TIMEOUT = int(os.environ.get("MEMORY_PROXY_TIMEOUT", "120"))

DB_LOCK = threading.RLock()

TOPIC_KEYWORDS = {
    "adb": ("adb", "android debug bridge", "usb debugging", "adb pull", "adb devices"),
    "wifi_direct": ("wifi direct", "wi-fi direct", "wifidirect"),
    "bluetooth_pan": ("bluetooth pan", "personal area network", "bthpan"),
    "screen_mirroring": ("scrcpy", "screen mirror", "mirroring", "cast"),
    "file_sharing": ("file sharing", "smb", "share", "robocopy", "copy-item"),
    "troubleshooting": ("error", "failed", "troubleshoot", "fix", "diagnose"),
    "network_basics": ("ipconfig", "netsh", "ping", "subnet", "firewall"),
}

CODE_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+.-]*)\s*\n(.*?)```", re.DOTALL)
THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s`\"']+")
ANDROID_PATH_RE = re.compile(r"(?<!\w)/(?:sdcard|storage|data|system|mnt)/[^\s`\"']+")
COMMAND_LINE_RE = re.compile(
    r"(?im)^\s*(?:adb|powershell|pwsh|cmd|netsh|ipconfig|ping|Get-[A-Za-z]+|New-Item|Start-Sleep|Copy-Item|robocopy)\b.*$"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(message: str, exc: Optional[BaseException] = None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{utc_now()}] {message}"
    if exc is not None:
        line += f" :: {type(exc).__name__}: {exc}"
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        if exc is not None:
            handle.write(traceback.format_exc() + "\n")
    print(line, flush=True)


def compact(text: str, limit: int) -> str:
    text = re.sub(r"\r\n?", "\n", str(text or "")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 18)].rstrip() + "\n...[truncated]"


def content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part)
    return json.dumps(content, ensure_ascii=False)


def strip_thinking(text: str) -> str:
    return THINK_RE.sub("", text or "").strip()


def stable_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def detect_topics(*texts: str) -> List[str]:
    combined = "\n".join(texts).lower()
    topics = [topic for topic, words in TOPIC_KEYWORDS.items() if any(word in combined for word in words)]
    return topics or ["general"]


def detect_code_languages(text: str) -> List[str]:
    languages = []
    for language, _ in CODE_FENCE_RE.findall(text or ""):
        lang = (language or "plain").strip().lower()
        if lang and lang not in languages:
            languages.append(lang)
    if "adb " in (text or "").lower() and "adb" not in languages:
        languages.append("adb")
    return languages or ["none"]


def extract_code_blocks(text: str, max_blocks: int = 3, max_each: int = 1200) -> List[str]:
    blocks = []
    for language, code in CODE_FENCE_RE.findall(text or ""):
        label = (language or "plain").strip() or "plain"
        blocks.append(f"```{label}\n{compact(code, max_each)}\n```")
        if len(blocks) >= max_blocks:
            break
    return blocks


def extract_paths_and_commands(text: str) -> Tuple[List[str], List[str]]:
    paths = []
    for pattern in (WINDOWS_PATH_RE, ANDROID_PATH_RE):
        for match in pattern.findall(text or ""):
            cleaned = match.rstrip(".,);]")
            if cleaned not in paths:
                paths.append(cleaned)
    commands = []
    for match in COMMAND_LINE_RE.findall(text or ""):
        cleaned = match.strip()
        if cleaned not in commands:
            commands.append(cleaned)
    return paths[:12], commands[:16]


def ollama_embed(texts: List[str]) -> List[List[float]]:
    response = requests.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBEDDING_MODEL, "input": texts},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    embeddings = body.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError(f"Ollama returned invalid embedding payload for {len(texts)} input(s)")
    return embeddings


def lancedb_connection():
    LANCEDB_DIR.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(LANCEDB_DIR))


def memory_table_exists(db: Any) -> bool:
    raw_names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    table_names = raw_names.tables if hasattr(raw_names, "tables") else raw_names
    return MEMORY_TABLE in table_names


def open_memory_table() -> Optional[Any]:
    db = lancedb_connection()
    if not memory_table_exists(db):
        return None
    return db.open_table(MEMORY_TABLE)


def memory_stats() -> Dict[str, Any]:
    with DB_LOCK:
        table = open_memory_table()
        if table is None:
            return {"table": MEMORY_TABLE, "exists": False, "rows": 0, "last_created_at": None}
        count = table.count_rows()
        last_created_at = None
        if count and count <= 5000:
            try:
                rows = table.to_arrow().select(["created_at"]).to_pylist()
                created_values = [row.get("created_at") for row in rows if row.get("created_at")]
                if created_values:
                    last_created_at = max(created_values)
            except Exception as exc:
                log("memory stats could not scan created_at", exc)
        return {"table": MEMORY_TABLE, "exists": True, "rows": count, "last_created_at": last_created_at}


def retrieve_memory(user_prompt: str) -> Tuple[List[Dict[str, Any]], List[float]]:
    query_vector = ollama_embed([compact(user_prompt, 4000)])[0]
    with DB_LOCK:
        table = open_memory_table()
        if table is None or table.count_rows() == 0:
            return [], query_vector
        rows = table.search(query_vector).limit(MEMORY_TOP_K).to_list()
    return rows, query_vector


def format_memory_block(rows: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not rows:
        return None

    remaining = MEMORY_BLOCK_MAX_CHARS
    chunks = []
    for index, row in enumerate(rows, start=1):
        text = compact(str(row.get("text", "")), min(700, max(200, remaining)))
        if not text:
            continue
        meta = f"memory {index}"
        if row.get("created_at"):
            meta += f", {row['created_at']}"
        if row.get("topics"):
            meta += f", topics={row['topics']}"
        distance = row.get("_distance")
        if isinstance(distance, (int, float)):
            meta += f", distance={distance:.4f}"
        chunk = f"[{meta}]\n{text}"
        chunks.append(chunk)
        remaining -= len(chunk)
        if remaining <= 200:
            break

    if not chunks:
        return None

    content = (
        "Relevant prior memory from the external LanceDB tank.\n"
        "Use it only when it helps answer the current request. Prefer the user's latest prompt "
        "and current workspace RAG context if there is any conflict.\n\n"
        + "\n\n---\n\n".join(chunks)
    )
    return {"role": "system", "content": content}


def looks_like_context_message(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "relevant context",
        "workspace context",
        "document context",
        "source:",
        "sources:",
        "context below",
        "use the following context",
        "provided context",
        "retrieved context",
        "chunk",
    )
    return len(text) > 500 and any(marker in lowered for marker in markers)


def latest_user_message(messages: List[Dict[str, Any]]) -> Tuple[int, str]:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index, content_to_text(messages[index].get("content"))
    if messages:
        return len(messages) - 1, content_to_text(messages[-1].get("content"))
    return -1, ""


def rewrite_payload(payload: Dict[str, Any], memory_rows: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return dict(payload), {"latest_user": "", "original_count": 0, "rewritten_count": 0, "dropped_count": 0}

    latest_index, latest_user = latest_user_message(messages)
    memory_block = format_memory_block(memory_rows)
    rewritten_messages: List[Dict[str, Any]] = []

    for index, message in enumerate(messages):
        if index == latest_index:
            continue
        role = message.get("role")
        text = content_to_text(message.get("content"))
        if role == "system" or looks_like_context_message(text):
            rewritten_messages.append(message)

    if memory_block is not None:
        rewritten_messages.append(memory_block)

    if latest_index >= 0:
        rewritten_messages.append(messages[latest_index])

    rewritten = dict(payload)
    rewritten["messages"] = rewritten_messages
    rewritten.setdefault("model", "Bonsai-8B-gguf")

    return rewritten, {
        "latest_user": latest_user,
        "original_count": len(messages),
        "rewritten_count": len(rewritten_messages),
        "dropped_count": max(0, len(messages) - len(rewritten_messages)),
        "memory_rows": len(memory_rows),
    }


def build_memory_record(user_prompt: str, assistant_text: str) -> Dict[str, Any]:
    clean_answer = strip_thinking(assistant_text)
    topics = detect_topics(user_prompt, clean_answer)
    languages = detect_code_languages(clean_answer)
    paths, commands = extract_paths_and_commands(user_prompt + "\n" + clean_answer)
    code_blocks = extract_code_blocks(clean_answer)

    retained = []
    if paths:
        retained.append("Paths: " + "; ".join(paths))
    if commands:
        retained.append("Commands: " + " | ".join(compact(command, 160) for command in commands))
    if not retained:
        retained.append("No explicit paths or shell commands detected.")

    parts = [
        "Memory type: distilled_turn",
        f"Created: {utc_now()}",
        f"Topics: {', '.join(topics)}",
        f"Code languages: {', '.join(languages)}",
        "",
        "User intent:",
        compact(user_prompt, 900),
        "",
        "Retained details:",
        "\n".join(f"- {item}" for item in retained),
    ]
    if code_blocks:
        parts.extend(["", "Code snippets to remember:", "\n\n".join(code_blocks)])
    parts.extend(["", "Assistant outcome:", compact(clean_answer, 1500)])
    text = compact("\n".join(parts), MEMORY_RECORD_MAX_CHARS)

    turn_hash = stable_hash(user_prompt + "\n---\n" + clean_answer)
    return {
        "id": f"memory-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{turn_hash[:12]}",
        "text": text,
        "created_at": utc_now(),
        "turn_hash": turn_hash,
        "topics": ",".join(topics),
        "code_languages": ",".join(languages),
        "importance": 0.9 if code_blocks or commands else 0.6,
        "source": "memory_proxy",
    }


def insert_memory(user_prompt: str, assistant_text: str) -> Optional[str]:
    if not user_prompt.strip() or not assistant_text.strip():
        return None
    row = build_memory_record(user_prompt, assistant_text)
    row["vector"] = ollama_embed([row["text"]])[0]
    with DB_LOCK:
        db = lancedb_connection()
        if memory_table_exists(db):
            db.open_table(MEMORY_TABLE).add([row])
        else:
            db.create_table(MEMORY_TABLE, [row])
    log(f"stored memory row {row['id']} topics={row['topics']}")
    return str(row["id"])


def parse_streamed_openai_content(stream_bytes: bytes) -> str:
    text_parts: List[str] = []
    decoded = stream_bytes.decode("utf-8", errors="replace")
    for raw_line in decoded.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in payload.get("choices", []):
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            content = delta.get("content") or message.get("content")
            if content:
                text_parts.append(str(content))
    return "".join(text_parts)


def extract_response_text(response_json: Dict[str, Any]) -> str:
    parts: List[str] = []
    for choice in response_json.get("choices", []):
        message = choice.get("message") or {}
        content = message.get("content")
        if content:
            parts.append(str(content))
    return "\n".join(parts)


def check_dependency_urls() -> None:
    try:
        requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5).raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Ollama is unavailable at {OLLAMA_BASE}: {exc}") from exc
    try:
        requests.get(f"{BONSAI_BASE}/models", timeout=5).raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Bonsai is unavailable at {BONSAI_BASE}: {exc}") from exc


def flush_bonsai_slot() -> Dict[str, Any]:
    url = f"{BONSAI_SERVER}/slots/0?action=erase"
    try:
        response = requests.post(url, timeout=8)
        if response.status_code in (404, 405):
            response = requests.get(url, timeout=8)
        ok = 200 <= response.status_code < 300
        if ok:
            log("slot erase succeeded")
        elif response.status_code == 501:
            log("slot erase unsupported by this llama-server build or launch mode; proxy still drops raw chat history before each request")
        else:
            log(f"slot erase returned {response.status_code}")
        return {"ok": ok, "status_code": response.status_code}
    except Exception as exc:
        log("slot erase failed", exc)
        return {"ok": False, "error": str(exc)}


class MemoryProxyHandler(BaseHTTPRequestHandler):
    server_version = "NetworkIntegrationMemoryProxy/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        log(f"{self.client_address[0]} {fmt % args}")

    def _send_bytes(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.handle_health()
        elif path == "/memory/stats":
            self._send_json(200, memory_stats())
        elif path == "/v1/models":
            self.proxy_models()
        else:
            self._send_json(404, {"error": f"Unknown endpoint: {path}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/chat/completions":
            self.handle_chat_completions()
        else:
            self._send_json(404, {"error": f"Unknown endpoint: {path}"})

    def handle_health(self) -> None:
        health: Dict[str, Any] = {
            "online": True,
            "proxy": "ok",
            "bonsai_base": BONSAI_BASE,
            "ollama_base": OLLAMA_BASE,
            "lancedb_dir": str(LANCEDB_DIR),
            "memory_table": MEMORY_TABLE,
        }
        status = 200
        try:
            requests.get(f"{BONSAI_BASE}/models", timeout=5).raise_for_status()
            health["bonsai"] = "ok"
        except Exception as exc:
            status = 502
            health["bonsai"] = f"error: {exc}"
        try:
            requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5).raise_for_status()
            health["ollama"] = "ok"
        except Exception as exc:
            status = 502
            health["ollama"] = f"error: {exc}"
        try:
            health["memory"] = memory_stats()
        except Exception as exc:
            status = 502
            health["memory"] = f"error: {exc}"
        self._send_json(status, health)

    def proxy_models(self) -> None:
        try:
            response = requests.get(f"{BONSAI_BASE}/models", timeout=REQUEST_TIMEOUT)
            self._send_bytes(
                response.status_code,
                response.content,
                response.headers.get("Content-Type", "application/json"),
            )
        except Exception as exc:
            self._send_json(502, {"error": f"Bonsai model endpoint failed: {exc}"})

    def handle_chat_completions(self) -> None:
        try:
            payload = self._read_json()
        except Exception as exc:
            self._send_json(400, {"error": f"Invalid JSON request: {exc}"})
            return

        try:
            check_dependency_urls()
        except Exception as exc:
            self._send_json(502, {"error": str(exc)})
            return

        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        _, latest_user = latest_user_message(messages)
        memory_rows: List[Dict[str, Any]] = []
        try:
            memory_rows, _ = retrieve_memory(latest_user)
        except Exception as exc:
            log("memory retrieval failed; continuing without memory block", exc)

        rewritten, meta = rewrite_payload(payload, memory_rows)
        stream = bool(rewritten.get("stream"))
        log(
            "chat rewrite "
            f"original_messages={meta.get('original_count')} "
            f"rewritten_messages={meta.get('rewritten_count')} "
            f"dropped={meta.get('dropped_count')} "
            f"memory_rows={meta.get('memory_rows')} "
            f"stream={stream}"
        )

        if stream:
            self.forward_streaming_chat(rewritten, latest_user)
        else:
            self.forward_json_chat(rewritten, latest_user)

    def forward_json_chat(self, payload: Dict[str, Any], latest_user: str) -> None:
        assistant_text = ""
        try:
            response = requests.post(
                f"{BONSAI_BASE}/chat/completions",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code >= 500:
                self._send_json(502, {"error": response.text})
                return
            body = response.json()
            assistant_text = extract_response_text(body)
            self._send_bytes(
                response.status_code,
                response.content,
                response.headers.get("Content-Type", "application/json"),
            )
        except Exception as exc:
            self._send_json(502, {"error": f"Bonsai chat request failed: {exc}"})
            return
        finally:
            if assistant_text:
                try:
                    insert_memory(latest_user, assistant_text)
                except Exception as exc:
                    log("memory write failed after non-streaming response", exc)
            flush_bonsai_slot()

    def forward_streaming_chat(self, payload: Dict[str, Any], latest_user: str) -> None:
        stream_buffer = bytearray()
        assistant_text = ""
        try:
            with requests.post(
                f"{BONSAI_BASE}/chat/completions",
                json=payload,
                stream=True,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status_code >= 500:
                    self._send_json(502, {"error": response.text})
                    return

                self.send_response(response.status_code)
                self.send_header("Content-Type", response.headers.get("Content-Type", "text/event-stream"))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()

                for chunk in response.iter_content(chunk_size=None):
                    if not chunk:
                        continue
                    stream_buffer.extend(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
            assistant_text = parse_streamed_openai_content(bytes(stream_buffer))
        except (BrokenPipeError, ConnectionResetError):
            log("client disconnected during streaming response")
        except Exception as exc:
            if not stream_buffer:
                self._send_json(502, {"error": f"Bonsai streaming chat failed: {exc}"})
            else:
                log("Bonsai streaming chat failed after partial response", exc)
            return
        finally:
            if assistant_text:
                try:
                    insert_memory(latest_user, assistant_text)
                except Exception as exc:
                    log("memory write failed after streaming response", exc)
            flush_bonsai_slot()


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log(
        "starting memory proxy "
        f"host={HOST} port={PORT} bonsai={BONSAI_BASE} ollama={OLLAMA_BASE} "
        f"table={MEMORY_TABLE}"
    )
    server = ThreadingHTTPServer((HOST, PORT), MemoryProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("memory proxy stopped by keyboard interrupt")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
