$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $Root "logs\api.log"
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\install.ps1 first."
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

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
$env:PYTHONPATH = Join-Path $Root "app"
$HostName = if ($env:WHISPER_API_HOST) { $env:WHISPER_API_HOST } else { "127.0.0.1" }
$Port = if ($env:WHISPER_API_PORT) { $env:WHISPER_API_PORT } else { "8088" }
& $Python -m uvicorn api:app --host $HostName --port $Port 2>&1 | Tee-Object -FilePath $Log -Append

