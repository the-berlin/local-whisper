$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "api.pid"
$EnvFile = Join-Path $Root ".env"

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

$hostName = if ($env:WHISPER_API_HOST) { $env:WHISPER_API_HOST } else { "127.0.0.1" }
$port = if ($env:WHISPER_API_PORT) { [int]$env:WHISPER_API_PORT } else { 8088 }
$pidValue = if (Test-Path $PidFile) { Get-Content -Path $PidFile -ErrorAction SilentlyContinue } else { $null }
$process = if ($pidValue) { Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue } else { $null }
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $owner = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [pscustomobject]@{ Pid = $_.OwningProcess; Process = $owner.ProcessName; Path = $owner.Path }
}

[pscustomobject]@{
    Running = [bool]$process
    PidFilePid = $pidValue
    Url = "http://${hostName}:${port}"
    Health = "http://${hostName}:${port}/health"
    Log = Join-Path $Root "logs\api.log"
    StdOutLog = Join-Path $Root "logs\api.stdout.log"
    StdErrLog = Join-Path $Root "logs\api.stderr.log"
    PortListeners = @($listeners)
} | Format-List
