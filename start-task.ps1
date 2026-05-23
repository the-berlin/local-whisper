param(
    [string]$TaskName = "LocalWhisperTranscriber"
)

$ErrorActionPreference = "Stop"
Start-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task started: $TaskName"
