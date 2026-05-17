$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ProxyScript = Join-Path $RepoRoot "src\memory_proxy.py"
$LogDir = if ($env:NETWORK_COACH_LOG_DIR) { $env:NETWORK_COACH_LOG_DIR } else { Join-Path $RepoRoot "logs" }
$Port = 8081

if (-not (Test-Path -LiteralPath $ProxyScript)) {
  throw "memory_proxy.py was not found at $ProxyScript"
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  throw "python was not found on PATH."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
  $pids = $listener | Select-Object -ExpandProperty OwningProcess -Unique
  Write-Host "Memory proxy appears to already be listening on port $Port via PID(s): $($pids -join ', ')"
  exit 0
}

$env:MEMORY_PROXY_HOST = "127.0.0.1"
$env:MEMORY_PROXY_PORT = "$Port"
$env:BONSAI_OPENAI_BASE = "http://127.0.0.1:8080/v1"
$env:OLLAMA_BASE_PATH = "http://127.0.0.1:11434"
$env:MEMORY_EMBEDDING_MODEL = "nomic-embed-text:latest"
$env:ANYTHINGLLM_STORAGE_DIR = Join-Path $env:APPDATA "anythingllm-desktop\storage"
$env:MEMORY_TABLE = "networkintegrationcoach_memory"
$env:MEMORY_PROXY_LOG = Join-Path $LogDir "memory_proxy.log"

$proc = Start-Process `
  -FilePath $python.Source `
  -ArgumentList @("-u", $ProxyScript) `
  -WindowStyle Hidden `
  -PassThru `
  -RedirectStandardOutput (Join-Path $LogDir "memory_proxy.out.log") `
  -RedirectStandardError (Join-Path $LogDir "memory_proxy.err.log")

Write-Host "Started memory proxy PID=$($proc.Id) at http://127.0.0.1:$Port/v1"
