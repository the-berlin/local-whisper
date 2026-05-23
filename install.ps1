param(
    [string]$PythonVersion = "3.12",
    [string]$PythonCommand = "",
    [switch]$InstallTask
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

function New-LocalVenv {
    if ($PythonCommand) {
        Write-Host "Creating venv with $PythonCommand..."
        & $PythonCommand -m venv $Venv
        return
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        Write-Host "Creating venv with Python $PythonVersion via py launcher..."
        py -$PythonVersion -m venv $Venv
        return
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Host "Creating venv with global python..."
        python -m venv $Venv
        return
    }

    throw "Python was not found. Install Python 3.12+ globally or pass -PythonCommand <path-to-python.exe>."
}

Write-Host "== Local Whisper Transcriber install =="
Write-Host "Root: $Root"

if (-not (Test-Path $Venv)) {
    New-LocalVenv
}

if (-not (Test-Path $Python)) {
    throw "Virtual environment was not created correctly: $Python"
}

Write-Host "Upgrading pip..."
& $Python -m pip install --upgrade pip

Write-Host "Installing dependencies..."
& $Pip install -r (Join-Path $Root "requirements.txt")

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Write-Host "Created .env from .env.example"
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "System ffmpeg is not in PATH. faster-whisper can still work through PyAV; install ffmpeg only if a specific format fails."
}

if ($InstallTask) {
    & (Join-Path $Root "install-task.ps1")
}

Write-Host "Install complete."
Write-Host "Run watcher: .\run-watch.ps1"
Write-Host "Run REST API: .\run-api.ps1"
