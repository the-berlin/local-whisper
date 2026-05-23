$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$Log = Join-Path $LogDir "api.log"
$PidFile = Join-Path $Root "api.pid"
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $Python)) {
    & (Join-Path $Root "install.ps1")
}
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found after install: $Python"
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

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$PID | Set-Content -Path $PidFile -Encoding ASCII
$env:PYTHONPATH = Join-Path $Root "app"
$HostName = if ($env:WHISPER_API_HOST) { $env:WHISPER_API_HOST } else { "127.0.0.1" }
$Port = if ($env:WHISPER_API_PORT) { $env:WHISPER_API_PORT } else { "8088" }

try {
    $StdOutLog = Join-Path $LogDir "api.stdout.log"
    $StdErrLog = Join-Path $LogDir "api.stderr.log"
    Add-Content -Path $Log -Encoding UTF8 -Value "[$(Get-Date -Format s)] Starting Local Whisper API on ${HostName}:${Port}"
    $arguments = @("-m", "uvicorn", "api:app", "--host", $HostName, "--port", $Port)
    $process = Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $StdOutLog -RedirectStandardError $StdErrLog -PassThru
    Add-Content -Path $Log -Encoding UTF8 -Value "[$(Get-Date -Format s)] Python API process PID: $($process.Id)"
    $process.WaitForExit()
    $process.Refresh()
    Add-Content -Path $Log -Encoding UTF8 -Value "[$(Get-Date -Format s)] Python API process exited with code: $($process.ExitCode)"
    exit $process.ExitCode
}
finally {
    if (Test-Path $PidFile) {
        $current = Get-Content -Path $PidFile -ErrorAction SilentlyContinue
        if ($current -eq [string]$PID) {
            Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        }
    }
}



