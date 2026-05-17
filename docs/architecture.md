# Architecture

NetworkIntegrationCoach Memory RAG uses two separate LanceDB roles:

- The AnythingLLM workspace table stores the coding/networking knowledge base.
- The memory proxy table stores distilled turn memory.

The separation matters. Dataset RAG answers "what do the docs/examples say?" External memory answers "what did we already decide, debug, or configure?"

## Request Lifecycle

1. The user sends a message in AnythingLLM.
2. AnythingLLM retrieves relevant workspace chunks from its normal LanceDB table.
3. AnythingLLM sends an OpenAI-compatible request to the memory proxy.
4. The proxy extracts the latest user message.
5. The proxy embeds the latest user message through Ollama.
6. The proxy retrieves the top relevant records from `networkintegrationcoach_memory`.
7. The proxy rewrites the prompt:
   - keep system instructions,
   - inject a compact "Relevant prior memory" system block,
   - preserve the current AnythingLLM RAG context,
   - keep the latest user message,
   - drop old raw user/assistant messages.
8. The proxy forwards the rewritten request to Bonsai llama-server.
9. The proxy streams or returns the answer to AnythingLLM.
10. The proxy writes a distilled memory record to LanceDB.
11. The proxy calls `POST /slots/0?action=erase`.

## Why Not Use KV State as Long-Term Memory?

llama.cpp slot save and restore can persist slot state, but restored state still has to fit in the active context window. That makes it useful for reuse, not for unbounded memory.

This repo uses semantic memory because it is inspectable, compact, searchable, and independent of the model runtime.

## Prompt Rewriting Policy

The proxy is conservative:

- It keeps system messages.
- It keeps the latest user message.
- It injects retrieved memory as a system message.
- It drops old raw chat turns.
- It lets AnythingLLM keep controlling current workspace RAG.

This gives continuity without allowing stale chat history to crowd the active context.

## Memory Row Shape

Each memory row contains:

| Field | Purpose |
| --- | --- |
| `id` | Stable row identifier |
| `vector` | Ollama embedding |
| `text` | Distilled memory text |
| `created_at` | UTC timestamp |
| `turn_hash` | Hash of user plus assistant text |
| `topics` | Detected topic labels |
| `code_languages` | Detected code block languages |
| `importance` | Simple heuristic importance score |
| `source` | Memory source label |

## Failure Behavior

Memory retrieval and write failures are logged but do not block the main response when Bonsai is healthy. Bonsai and Ollama connection failures return HTTP 502.
