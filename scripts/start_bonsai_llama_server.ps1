$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DefaultLlamaDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe"
$DefaultOllamaBlob = Join-Path $env:USERPROFILE ".ollama\models\blobs\sha256-284a335aa3fb2ced3b1b01fcb40b08aa783e3b70832767f0dd2e3fdfa134bd54"

$Server = if ($env:LLAMA_SERVER_EXE) { $env:LLAMA_SERVER_EXE } else { Join-Path $DefaultLlamaDir "llama-server.exe" }
$Model = if ($env:BONSAI_GGUF_PATH) { $env:BONSAI_GGUF_PATH } else { $DefaultOllamaBlob }
$LogDir = if ($env:NETWORK_COACH_LOG_DIR) { $env:NETWORK_COACH_LOG_DIR } else { Join-Path $RepoRoot "logs" }
$SlotSaveDir = if ($env:NETWORK_COACH_SLOT_DIR) { $env:NETWORK_COACH_SLOT_DIR } else { Join-Path $RepoRoot "slot_state" }
$Port = 8080

if (-not (Test-Path -LiteralPath $Server)) {
  throw "llama-server.exe was not found at $Server. Set LLAMA_SERVER_EXE or install it with: winget install --id ggml.llamacpp --accept-source-agreements --accept-package-agreements --silent"
}

if (-not (Test-Path -LiteralPath $Model)) {
  throw "Bonsai GGUF was not found at $Model. Set BONSAI_GGUF_PATH or pull the known Ollama blob with: ollama pull hf.co/prism-ml/Bonsai-8B-gguf:Q1_0"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $SlotSaveDir | Out-Null

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
  $pids = $listener | Select-Object -ExpandProperty OwningProcess -Unique
  Write-Host "llama-server appears to already be listening on port $Port via PID(s): $($pids -join ', ')"
  exit 0
}

# VRAM-only strategy: -ngl 99 offloads all layers to GPU,
# --no-mmap prevents a redundant RAM copy of the weights,
# --flash-attn on uses efficient KV cache in VRAM.
# --parallel 1 prevents duplicate KV/cache allocations on 4 GB VRAM.
# --cache-ram 0 disables llama-server prompt cache so long-term memory stays in LanceDB.
# --no-cache-prompt keeps old prompts out of server-side reuse when supported by the build.
# --slot-save-path enables slot erase; the proxy erases after each turn and does not save KV state.
$args = @(
  "-m", $Model,
  "--host", "127.0.0.1",
  "--port", "$Port",
  "--ctx-size", "8192",
  "-ngl", "99",
  "--no-mmap",
  "--flash-attn", "on",
  "--parallel", "1",
  "--cache-ram", "0",
  "--no-cache-prompt",
  "--slot-save-path", $SlotSaveDir,
  "--alias", "Bonsai-8B-gguf"
)

$quotedArgs = $args | ForEach-Object {
  if ($_ -match '[\s"]') {
    '"' + ($_ -replace '"', '\"') + '"'
  } else {
    $_
  }
}

$proc = Start-Process `
  -FilePath $Server `
  -ArgumentList ($quotedArgs -join " ") `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput (Join-Path $LogDir "llama_server.out.log") `
  -RedirectStandardError (Join-Path $LogDir "llama_server.err.log")

Write-Host "Started llama-server PID=$($proc.Id) at http://127.0.0.1:$Port/v1"
