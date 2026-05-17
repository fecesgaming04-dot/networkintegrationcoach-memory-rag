$ErrorActionPreference = "Stop"

$StorageDir = if ($env:ANYTHINGLLM_STORAGE_DIR) {
  $env:ANYTHINGLLM_STORAGE_DIR
} else {
  Join-Path $env:APPDATA "anythingllm-desktop\storage"
}
$EnvPath = Join-Path $StorageDir ".env"

if (-not (Test-Path -LiteralPath $EnvPath)) {
  throw "AnythingLLM .env was not found at $EnvPath. Start AnythingLLM once, then rerun this script."
}

$backup = "$EnvPath.backup.$(Get-Date -Format 'yyyyMMddHHmmss')"
Copy-Item -LiteralPath $EnvPath -Destination $backup -Force

$settings = [ordered]@{
  LLM_PROVIDER = "generic-openai"
  GENERIC_OPEN_AI_BASE_PATH = "http://127.0.0.1:8081/v1"
  GENERIC_OPEN_AI_MODEL_PREF = "Bonsai-8B-gguf"
  GENERIC_OPEN_AI_MODEL_TOKEN_LIMIT = "8192"
  GENERIC_OPEN_AI_API_KEY = "none"
  GENERIC_OPEN_AI_MAX_TOKENS = "4096"
  EMBEDDING_ENGINE = "ollama"
  EMBEDDING_BASE_PATH = "http://127.0.0.1:11434"
  EMBEDDING_MODEL_PREF = "nomic-embed-text:latest"
  VECTOR_DB = "lancedb"
}

$lines = @(Get-Content -LiteralPath $EnvPath)
foreach ($key in $settings.Keys) {
  $value = $settings[$key]
  $line = "$key='$value'"
  $index = -1
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*$([regex]::Escape($key))=") {
      $index = $i
      break
    }
  }
  if ($index -ge 0) {
    $lines[$index] = $line
  } else {
    $lines += $line
  }
}

Set-Content -LiteralPath $EnvPath -Value $lines -Encoding UTF8
Write-Host "Updated $EnvPath"
Write-Host "Backup written to $backup"
Write-Host "Restart AnythingLLM Desktop for the changes to take effect."
