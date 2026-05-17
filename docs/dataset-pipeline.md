# Dataset Pipeline

The dataset tools build a synthetic phone-to-laptop networking guide. The generated full dataset is intentionally not committed.

## Generate

```powershell
python .\tools\generate_network_guide_dataset.py --records 2000000
```

Default output:

```text
data\network_guide_2M.jsonl
```

## Validate

```powershell
python .\tools\validate_dataset.py
```

Validation checks:

- JSONL shape.
- Required fields: `instruction`, `output`, `topic`.
- Expected record count.
- Topic balance.
- Difficulty-level balance.

## Chunk for Manual AnythingLLM Upload

```powershell
python .\tools\chunk_dataset_for_anythingllm.py
```

Default output:

```text
data\anythingllm_chunks\
```

## Embed Directly Into AnythingLLM LanceDB

```powershell
python .\tools\embed_dataset_to_anythingllm.py --reset
```

The embedder:

- uses Ollama `/api/embed`,
- canonicalizes repeated examples to reduce embedding calls,
- writes LanceDB rows into the AnythingLLM workspace table,
- optionally writes `document_vectors` rows in the AnythingLLM SQLite database.

Use `--limit` for a smaller test:

```powershell
python .\tools\embed_dataset_to_anythingllm.py --limit 10000 --reset
```

## Smoke Test Fixture

For quick tests, use:

```text
examples\test_network_guide.jsonl
```

Example:

```powershell
python .\tools\validate_dataset.py --input .\examples\test_network_guide.jsonl --expected 42 --summary .\examples\test_network_guide.summary.json
```
