$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ScriptRoot = $PSScriptRoot
$OllamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$AnythingLlmExe = Join-Path $env:LOCALAPPDATA "Programs\AnythingLLM\AnythingLLM.exe"
$BonsaiServerScript = Join-Path $ScriptRoot "start_bonsai_llama_server.ps1"
$MemoryProxyScript = Join-Path $ScriptRoot "start_memory_proxy.ps1"
$AnythingUrl = "http://127.0.0.1:3001"
$OllamaUrl = "http://127.0.0.1:11434/api/tags"
$BonsaiUrl = "http://127.0.0.1:8080/v1/models"
$MemoryProxyUrl = "http://127.0.0.1:8081/health"

function Test-Endpoint {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Uri
  )

  try {
    Invoke-RestMethod -Uri $Uri -Method Get -TimeoutSec 3 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Wait-Endpoint {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$Uri,
    [int]$TimeoutSeconds = 60
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    if (Test-Endpoint -Uri $Uri) {
      Write-LauncherLog "$Name is online."
      return $true
    }
    Start-Sleep -Milliseconds 800
    [System.Windows.Forms.Application]::DoEvents()
  } while ((Get-Date) -lt $deadline)

  Write-LauncherLog "$Name did not respond before timeout."
  return $false
}

function Write-LauncherLog {
  param([string]$Message)

  $timestamp = Get-Date -Format "HH:mm:ss"
  $script:LogBox.AppendText("[$timestamp] $Message`r`n")
  $script:LogBox.SelectionStart = $script:LogBox.TextLength
  $script:LogBox.ScrollToCaret()
  [System.Windows.Forms.Application]::DoEvents()
}

function Set-StatusLabel {
  param(
    [System.Windows.Forms.Label]$Label,
    [string]$Text,
    [System.Drawing.Color]$Color
  )

  $Label.Text = $Text
  $Label.ForeColor = $Color
}

function Refresh-Status {
  $green = [System.Drawing.Color]::FromArgb(22, 130, 74)
  $red = [System.Drawing.Color]::FromArgb(178, 34, 34)

  if (Test-Endpoint -Uri $OllamaUrl) {
    Set-StatusLabel $script:OllamaStatus "Ollama: online" $green
  } else {
    Set-StatusLabel $script:OllamaStatus "Ollama: offline" $red
  }

  if (Test-Endpoint -Uri $BonsaiUrl) {
    Set-StatusLabel $script:BonsaiStatus "Bonsai: online" $green
  } else {
    Set-StatusLabel $script:BonsaiStatus "Bonsai: offline" $red
  }

  if (Test-Endpoint -Uri $MemoryProxyUrl) {
    Set-StatusLabel $script:MemoryStatus "Memory: online" $green
  } else {
    Set-StatusLabel $script:MemoryStatus "Memory: offline" $red
  }

  if (Test-Endpoint -Uri "$AnythingUrl/api/ping") {
    Set-StatusLabel $script:AnythingStatus "AnythingLLM: online" $green
  } else {
    Set-StatusLabel $script:AnythingStatus "AnythingLLM: offline" $red
  }
}

function Stop-ListenerOnPort {
  param([int]$Port)

  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($ownerPid in ($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
    if ($ownerPid) {
      Get-Process -Id $ownerPid -ErrorAction SilentlyContinue | Stop-Process -Force
    }
  }
}

function Start-NetworkCoach {
  $script:LaunchButton.Enabled = $false
  $script:LaunchButton.Text = "Launching..."

  try {
    Write-LauncherLog "Starting NetworkIntegrationCoach environment."

    if (-not (Test-Path -LiteralPath $OllamaExe)) {
      throw "Ollama executable not found at $OllamaExe"
    }
    if (-not (Test-Path -LiteralPath $AnythingLlmExe)) {
      throw "AnythingLLM executable not found at $AnythingLlmExe"
    }
    if (-not (Test-Path -LiteralPath $BonsaiServerScript)) {
      throw "Bonsai server script not found at $BonsaiServerScript"
    }
    if (-not (Test-Path -LiteralPath $MemoryProxyScript)) {
      throw "Memory proxy script not found at $MemoryProxyScript"
    }

    if (-not (Test-Endpoint -Uri $OllamaUrl)) {
      Write-LauncherLog "Starting Ollama serve."
      Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    } else {
      Write-LauncherLog "Ollama is already running."
    }

    if (-not (Wait-Endpoint -Name "Ollama" -Uri $OllamaUrl -TimeoutSeconds 60)) {
      throw "Ollama did not become available at $OllamaUrl"
    }

    if (-not (Test-Endpoint -Uri $BonsaiUrl)) {
      Write-LauncherLog "Starting Bonsai llama-server."
      Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $BonsaiServerScript
      ) -WindowStyle Hidden | Out-Null
    } else {
      Write-LauncherLog "Bonsai llama-server is already running."
    }

    if (-not (Wait-Endpoint -Name "Bonsai" -Uri $BonsaiUrl -TimeoutSeconds 90)) {
      throw "Bonsai did not become available at $BonsaiUrl"
    }

    if (-not (Test-Endpoint -Uri $MemoryProxyUrl)) {
      Write-LauncherLog "Starting semantic memory proxy."
      Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $MemoryProxyScript
      ) -WindowStyle Hidden | Out-Null
    } else {
      Write-LauncherLog "Semantic memory proxy is already running."
    }

    if (-not (Wait-Endpoint -Name "Memory proxy" -Uri $MemoryProxyUrl -TimeoutSeconds 60)) {
      throw "Memory proxy did not become available at $MemoryProxyUrl"
    }

    if (-not (Test-Endpoint -Uri "$AnythingUrl/api/ping")) {
      Write-LauncherLog "Starting AnythingLLM Desktop."
      Start-Process -FilePath $AnythingLlmExe | Out-Null
    } else {
      Write-LauncherLog "AnythingLLM is already running."
    }

    if (-not (Wait-Endpoint -Name "AnythingLLM" -Uri "$AnythingUrl/api/ping" -TimeoutSeconds 150)) {
      throw "AnythingLLM did not become available at $AnythingUrl"
    }

    Refresh-Status
    Write-LauncherLog "Ready. NetworkIntegrationCoach should now be open."
  } catch {
    Write-LauncherLog "Launch failed: $($_.Exception.Message)"
    [System.Windows.Forms.MessageBox]::Show(
      $_.Exception.Message,
      "NetworkIntegrationCoach launch failed",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
  } finally {
    $script:LaunchButton.Enabled = $true
    $script:LaunchButton.Text = "Launch Network Coach"
    Refresh-Status
  }
}

function Stop-NetworkCoach {
  $answer = [System.Windows.Forms.MessageBox]::Show(
    "Stop AnythingLLM, semantic memory proxy, Bonsai llama-server, Ollama, and the Ollama tray app?",
    "Stop local services",
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
  )

  if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
    return
  }

  Stop-ListenerOnPort -Port 8081

  foreach ($name in @("AnythingLLM", "llama-server", "ollama", "ollama app")) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
  }

  Write-LauncherLog "Stopped local NetworkIntegrationCoach processes."
  Refresh-Status
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "NetworkIntegrationCoach Launcher"
$form.StartPosition = "CenterScreen"
$form.ClientSize = New-Object System.Drawing.Size(560, 420)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = "NetworkIntegrationCoach"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(22, 18)
$title.Size = New-Object System.Drawing.Size(510, 36)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Launches Ollama, Bonsai, semantic memory, and AnythingLLM for the Android networking coach."
$subtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$subtitle.Location = New-Object System.Drawing.Point(24, 58)
$subtitle.Size = New-Object System.Drawing.Size(510, 22)
$form.Controls.Add($subtitle)

$script:LaunchButton = New-Object System.Windows.Forms.Button
$script:LaunchButton.Text = "Launch Network Coach"
$script:LaunchButton.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$script:LaunchButton.Location = New-Object System.Drawing.Point(28, 98)
$script:LaunchButton.Size = New-Object System.Drawing.Size(500, 58)
$script:LaunchButton.Add_Click({ Start-NetworkCoach })
$form.Controls.Add($script:LaunchButton)

$openButton = New-Object System.Windows.Forms.Button
$openButton.Text = "Open AnythingLLM"
$openButton.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$openButton.Location = New-Object System.Drawing.Point(28, 166)
$openButton.Size = New-Object System.Drawing.Size(155, 34)
$openButton.Add_Click({ 
  $proc = Get-Process AnythingLLM -ErrorAction SilentlyContinue
  if ($proc) { Write-LauncherLog "AnythingLLM is already open." }
  else { Start-Process $AnythingLlmExe }
})
$form.Controls.Add($openButton)

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = "Refresh Status"
$refreshButton.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$refreshButton.Location = New-Object System.Drawing.Point(202, 166)
$refreshButton.Size = New-Object System.Drawing.Size(155, 34)
$refreshButton.Add_Click({ Refresh-Status })
$form.Controls.Add($refreshButton)

$stopButton = New-Object System.Windows.Forms.Button
$stopButton.Text = "Stop Services"
$stopButton.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$stopButton.Location = New-Object System.Drawing.Point(373, 166)
$stopButton.Size = New-Object System.Drawing.Size(155, 34)
$stopButton.Add_Click({ Stop-NetworkCoach })
$form.Controls.Add($stopButton)

$script:OllamaStatus = New-Object System.Windows.Forms.Label
$script:OllamaStatus.Location = New-Object System.Drawing.Point(30, 214)
$script:OllamaStatus.Size = New-Object System.Drawing.Size(125, 24)
$script:OllamaStatus.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($script:OllamaStatus)

$script:BonsaiStatus = New-Object System.Windows.Forms.Label
$script:BonsaiStatus.Location = New-Object System.Drawing.Point(158, 214)
$script:BonsaiStatus.Size = New-Object System.Drawing.Size(125, 24)
$script:BonsaiStatus.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($script:BonsaiStatus)

$script:MemoryStatus = New-Object System.Windows.Forms.Label
$script:MemoryStatus.Location = New-Object System.Drawing.Point(286, 214)
$script:MemoryStatus.Size = New-Object System.Drawing.Size(125, 24)
$script:MemoryStatus.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($script:MemoryStatus)

$script:AnythingStatus = New-Object System.Windows.Forms.Label
$script:AnythingStatus.Location = New-Object System.Drawing.Point(414, 214)
$script:AnythingStatus.Size = New-Object System.Drawing.Size(130, 24)
$script:AnythingStatus.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($script:AnythingStatus)

$script:LogBox = New-Object System.Windows.Forms.TextBox
$script:LogBox.Location = New-Object System.Drawing.Point(28, 248)
$script:LogBox.Size = New-Object System.Drawing.Size(500, 142)
$script:LogBox.Multiline = $true
$script:LogBox.ScrollBars = "Vertical"
$script:LogBox.ReadOnly = $true
$script:LogBox.Font = New-Object System.Drawing.Font("Consolas", 9)
$form.Controls.Add($script:LogBox)

$form.Add_Shown({
  Write-LauncherLog "Launcher ready."
  Refresh-Status
})

[void]$form.ShowDialog()
