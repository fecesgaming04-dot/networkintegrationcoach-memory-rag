# Operations and Troubleshooting

## Start Order

The launcher starts services in this order:

1. Ollama.
2. Bonsai llama-server.
3. Memory proxy.
4. AnythingLLM Desktop.

This order matters because the proxy needs Bonsai and Ollama, and AnythingLLM needs the proxy.

## Stop Services

Use the GUI `Stop Services` button, or stop listeners manually:

```powershell
Get-NetTCPConnection -LocalPort 8080,8081,3001,11434 -State Listen
```

## Logs

Default logs are written under:

```text
logs\
```

Useful files:

| File | Meaning |
| --- | --- |
| `logs\llama_server.err.log` | llama-server startup and request details |
| `logs\llama_server.out.log` | llama-server stdout |
| `logs\memory_proxy.log` | proxy health, rewrite, memory write, and slot erase events |
| `logs\memory_proxy.err.log` | Python stderr |

## Confirm Prompt Cache Is Disabled

Search the Bonsai log:

```powershell
Select-String .\logs\llama_server.err.log -Pattern "prompt cache is disabled"
```

Expected:

```text
srv load_model: prompt cache is disabled - use `--cache-ram N` to enable it
```

## Confirm Slot Erase

Direct check:

```powershell
curl.exe -X POST "http://127.0.0.1:8080/slots/0?action=erase"
```

Expected:

```json
{"id_slot":0,"n_erased":0}
```

The proxy should also log:

```text
slot erase succeeded
```

## Common Problems

### `This server does not support slots action`

Start llama-server with `--slot-save-path`. The script already does this.

### Memory proxy is online but memory table is missing

That is normal before the first stored turn. Send one chat request through the proxy, then check:

```powershell
Invoke-RestMethod http://127.0.0.1:8081/memory/stats
```

### AnythingLLM answers but memory does not grow

Confirm AnythingLLM is pointed at the proxy:

```env
GENERIC_OPEN_AI_BASE_PATH='http://127.0.0.1:8081/v1'
```

Then restart AnythingLLM Desktop.

### Bonsai does not start

Check:

- `LLAMA_SERVER_EXE`
- `BONSAI_GGUF_PATH`
- GPU memory pressure
- `logs\llama_server.err.log`

### Responses are slow or unstable

Try:

- close heavy background apps,
- keep `--parallel 1`,
- lower AnythingLLM max tokens,
- reduce `MEMORY_TOP_K`,
- reduce `MEMORY_BLOCK_MAX_CHARS`.
