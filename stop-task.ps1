param(
    [string]$TaskName = "LocalWhisperTranscriber"
)

$ErrorActionPreference = "Stop"
Stop-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task stopped: $TaskName"
