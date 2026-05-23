$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StopScript = Join-Path $Root "stop-api.ps1"
$StartScript = Join-Path $Root "run-api.ps1"

Write-Host "Restarting Local Whisper API..."
& $StopScript
Start-Sleep -Seconds 2
& $StartScript
