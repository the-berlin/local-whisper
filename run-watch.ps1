$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $Root "logs\transcriber.log"

if (-not (Test-Path $Python)) {
    & (Join-Path $Root "install.ps1")
}
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found after install: $Python"
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
& $Python (Join-Path $Root "app\transcriber.py") --root $Root --mode watch 2>&1 | Tee-Object -FilePath $Log -Append
