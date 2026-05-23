$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    & (Join-Path $Root "install.ps1")
}
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found after install: $Python"
}

& $Python (Join-Path $Root "app\transcriber.py") --root $Root --mode once
