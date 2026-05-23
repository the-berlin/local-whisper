$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $Root "api-serve.ps1"
$PidFile = Join-Path $Root "api.pid"
$LogDir = Join-Path $Root "logs"
$Log = Join-Path $LogDir "api.log"
$EnvFile = Join-Path $Root ".env"

function Expand-EnvValue {
    param([string]$Value)
    return [regex]::Replace($Value, '\$\{([^}]+)\}', {
        param($Match)
        $name = $Match.Groups[1].Value
        $resolved = [Environment]::GetEnvironmentVariable($name, "Process")
        if ($resolved) { return $resolved }
        return $Match.Value
    })
}

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $key, $value = $line.Split("=", 2)
            if (-not [Environment]::GetEnvironmentVariable($key, "Process")) {
                [Environment]::SetEnvironmentVariable($key, (Expand-EnvValue $value.Trim('"').Trim("'")), "Process")
            }
        }
    }
}

$HostName = if ($env:WHISPER_API_HOST) { $env:WHISPER_API_HOST } else { "127.0.0.1" }
$Port = if ($env:WHISPER_API_PORT) { [int]$env:WHISPER_API_PORT } else { 18088 }

if (Test-Path $PidFile) {
    $existingPid = Get-Content -Path $PidFile -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue)) {
        Write-Host "Local Whisper API is already running. PID: $existingPid"
        Write-Host "Log: $Log"
        exit 0
    }
    Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    Write-Error "Cannot start Local Whisper API: ${HostName}:${Port} is already in use by PID $($listener.OwningProcess) ($($owner.ProcessName)). Run .\status-api.ps1 for details."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$process = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Script) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
$process.Id | Set-Content -Path $PidFile -Encoding ASCII
Write-Host "Local Whisper API started in background. PID: $($process.Id)"
Write-Host "URL: http://${HostName}:${Port}"
Write-Host "Log: $Log"
Write-Host "Stop: .\stop-api.ps1"

