$ErrorActionPreference = "Stop"
$ollama = if ($env:OLLAMA_EXE) { $env:OLLAMA_EXE } else { Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe" }
if (-not (Test-Path -LiteralPath $ollama)) {
  throw "Ollama executable was not found at $ollama. Set OLLAMA_EXE or install Ollama Desktop."
}
$env:PATH = "$(Split-Path $ollama);$env:PATH"
$models = @(
  "hf.co/prism-ml/Bonsai-8B-gguf:Q1_0",
  "nomic-embed-text:latest"
)
foreach ($model in $models) {
  $stamp = Get-Date -Format o
  "[$stamp] START pull $model"
  & $ollama pull $model
  if ($LASTEXITCODE -ne 0) { throw "ollama pull failed for $model with exit code $LASTEXITCODE" }
  $stamp = Get-Date -Format o
  "[$stamp] DONE pull $model"
}
& $ollama list
