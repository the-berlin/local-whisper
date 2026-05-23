param(
    [string]$PythonVersion = "3.12",
    [switch]$InstallTask
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Pip = Join-Path $Venv "Scripts\pip.exe"

Write-Host "== Local Whisper Transcriber install =="
Write-Host "Root: $Root"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' not found. Install Python 3.12 or add it to PATH."
}

if (-not (Test-Path $Venv)) {
    Write-Host "Creating venv with Python $PythonVersion..."
    py -$PythonVersion -m venv $Venv
}

Write-Host "Upgrading pip..."
& $Python -m pip install --upgrade pip

Write-Host "Installing faster-whisper dependencies..."
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

Write-Host "Install complete. Put audio files into: $Root\inbox"
Write-Host "Run manually: .\run-watch.ps1"

