# Windows Setup

This guide assumes Windows 11 and PowerShell.

## 1. Install Dependencies

Install Python 3.10 or newer, Git, Ollama Desktop, AnythingLLM Desktop, and llama.cpp.

llama.cpp server:

```powershell
winget install --id ggml.llamacpp --accept-source-agreements --accept-package-agreements
```

Python packages:

```powershell
python -m pip install -r requirements.txt
```

## 2. Pull Models

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pull_models.ps1
```

The default chat model is:

```text
hf.co/prism-ml/Bonsai-8B-gguf:Q1_0
```

The default embedding model is:

```text
nomic-embed-text
```

## 3. Configure Model Path If Needed

`start_bonsai_llama_server.ps1` has a fallback for the known Ollama blob path. If your model lives elsewhere, set:

```powershell
$env:BONSAI_GGUF_PATH = "C:\path\to\Bonsai-8B.gguf"
```

If llama-server is not in the winget path, set:

```powershell
$env:LLAMA_SERVER_EXE = "C:\path\to\llama-server.exe"
```

## 4. Configure AnythingLLM

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure_anythingllm_env.ps1
```

Restart AnythingLLM after changing `.env`.

## 5. Launch

```powershell
.\Launch NetworkIntegrationCoach.cmd
```

Then click `Launch Network Coach`.

## 6. Verify

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_stack.ps1
```
