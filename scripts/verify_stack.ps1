$ErrorActionPreference = "Stop"

function Test-JsonEndpoint {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$Uri
  )

  try {
    $response = Invoke-RestMethod -Uri $Uri -TimeoutSec 8
    [pscustomobject]@{
      Name = $Name
      Uri = $Uri
      Online = $true
      Detail = ($response | ConvertTo-Json -Compress -Depth 5)
    }
  } catch {
    [pscustomobject]@{
      Name = $Name
      Uri = $Uri
      Online = $false
      Detail = $_.Exception.Message
    }
  }
}

$checks = @(
  Test-JsonEndpoint -Name "Ollama" -Uri "http://127.0.0.1:11434/api/tags"
  Test-JsonEndpoint -Name "Bonsai" -Uri "http://127.0.0.1:8080/v1/models"
  Test-JsonEndpoint -Name "Memory proxy" -Uri "http://127.0.0.1:8081/health"
  Test-JsonEndpoint -Name "AnythingLLM" -Uri "http://127.0.0.1:3001/api/ping"
)

$checks | Select-Object Name,Online,Uri | Format-Table -AutoSize

if ($checks.Online -contains $false) {
  $checks | Where-Object { -not $_.Online } | Format-List
  exit 1
}

$slotErase = curl.exe -sS -o - -w "`nHTTP_STATUS:%{http_code}`n" -X POST "http://127.0.0.1:8080/slots/0?action=erase"
Write-Host "Slot erase:"
Write-Host $slotErase

$stats = Invoke-RestMethod -Uri "http://127.0.0.1:8081/memory/stats" -TimeoutSec 8
Write-Host "Memory stats:"
$stats | ConvertTo-Json -Depth 5
