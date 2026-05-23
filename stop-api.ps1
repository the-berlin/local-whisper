$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "api.pid"
$EnvFile = Join-Path $Root ".env"

function Stop-ProcessTree {
    param([int]$ProcessId)
    Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcessId } | ForEach-Object {
        Stop-ProcessTree -ProcessId $_.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Test-IsLocalWhisperProcess {
    param([int]$ProcessId)
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    return (($proc.ExecutablePath -like "$Root\*") -or ($proc.CommandLine -like "*$Root*") -or ($proc.CommandLine -like "*uvicorn api:app*"))
}

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $key, $value = $line.Split("=", 2)
            if (-not [Environment]::GetEnvironmentVariable($key, "Process")) {
                [Environment]::SetEnvironmentVariable($key, $value.Trim('"').Trim("'"), "Process")
            }
        }
    }
}
$Port = if ($env:WHISPER_API_PORT) { [int]$env:WHISPER_API_PORT } else { 8088 }
$stopped = $false

if (Test-Path $PidFile) {
    $pidValue = Get-Content -Path $PidFile -ErrorAction SilentlyContinue
    if ($pidValue -and (Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue)) {
        Stop-ProcessTree -ProcessId ([int]$pidValue)
        Write-Host "Local Whisper API stopped. PID: $pidValue"
        $stopped = $true
    }
    Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
}

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    $ownerPid = [int]$listener.OwningProcess
    if (Test-IsLocalWhisperProcess -ProcessId $ownerPid) {
        Stop-ProcessTree -ProcessId $ownerPid
        Write-Host "Local Whisper API listener stopped on port $Port. PID: $ownerPid"
        $stopped = $true
    } else {
        $owner = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        Write-Warning "Port $Port is used by PID $ownerPid ($($owner.ProcessName)), but it does not look like this Local Whisper instance. Not stopping it."
    }
}

if (-not $stopped) {
    Write-Host "Local Whisper API is not running."
}
