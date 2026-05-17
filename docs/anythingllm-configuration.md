# AnythingLLM Configuration

AnythingLLM should talk to the memory proxy, not directly to Bonsai.

## Required Values

```env
LLM_PROVIDER='generic-openai'
GENERIC_OPEN_AI_BASE_PATH='http://127.0.0.1:8081/v1'
GENERIC_OPEN_AI_MODEL_PREF='Bonsai-8B-gguf'
GENERIC_OPEN_AI_API_KEY='none'
GENERIC_OPEN_AI_MODEL_TOKEN_LIMIT='8192'
GENERIC_OPEN_AI_MAX_TOKENS='4096'

EMBEDDING_ENGINE='ollama'
EMBEDDING_BASE_PATH='http://127.0.0.1:11434'
EMBEDDING_MODEL_PREF='nomic-embed-text:latest'
VECTOR_DB='lancedb'
```

Use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure_anythingllm_env.ps1
```

The script backs up the current `.env` before writing changes.

## Workspace Table

The expected workspace slug is:

```text
networkintegrationcoach
```

The memory proxy does not overwrite this table. It creates a separate table:

```text
networkintegrationcoach_memory
```

## Why Generic OpenAI?

AnythingLLM already knows how to call OpenAI-compatible APIs. The proxy implements the minimum compatible surface:

- `/v1/models`
- `/v1/chat/completions`

That lets AnythingLLM keep its UI and RAG pipeline while the proxy controls memory behavior.
