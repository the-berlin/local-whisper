# Local Whisper Transcriber

Offline local transcription service for Windows Platform, including Windows Server, with NVIDIA GPU acceleration. It uses `faster-whisper`, CUDA through `ctranslate2`, and stores downloaded Whisper models locally in `models`.

## Quick Start

```powershell
cd <install-dir>
.\install.ps1
.\run-watch.ps1
```

Put audio or video files into `inbox`. Batch folders are supported, for example `inbox\12`; the same folder structure is preserved in `out`, `archive`, and `failed`.

Results are written to `out\<subfolder>\<file-name>`:

- `transcript.txt` - plain transcript text
- `subtitles.srt` - SRT subtitles
- `segments.json` - timestamped segments and metadata
- `transcript.polished.txt` - created only when LM Studio polishing is enabled

After successful processing, the source file is moved to `archive`. Failed files are moved to `failed`, with a matching `*.reason.txt` file.

## GPU Profiles

The local `.env` file is not stored in git. After cloning, copy the closest profile:

```powershell
Copy-Item .env.rtx3090.example .env
```

The RTX 3090 24 GB profile uses:

```text
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
```

For RTX 4060 8 GB, use `.env.rtx4060.example`; it uses `int8_float16` so `large-v3` fits into VRAM more reliably.

## Watcher Autostart

On Windows Platform, the watcher is best managed through Windows Scheduled Task because a plain Python script is not an SCM service.

```powershell
cd <install-dir>
.\install-task.ps1
```

Task management:

```powershell
.\status-task.ps1
.\start-task.ps1
.\stop-task.ps1
.\uninstall-task.ps1
```

The task is named `LocalWhisperTranscriber` and starts `run-watch.ps1` when Windows starts.

## Migration To Windows Platform, Including Windows Server, With RTX 3090

1. Install the latest NVIDIA driver for RTX 3090.
2. Install Python 3.12 x64 and enable the Python Launcher `py`.
3. Clone the repository into the target folder.
4. Copy the RTX 3090 profile:

```powershell
Copy-Item .env.rtx3090.example .env
```

5. Review `.env`.
6. Install dependencies:

```powershell
.\install.ps1
```

7. Warm up the model:

```powershell
.\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16', download_root=r'.\models'); print('ok')"
```

8. Enable watcher autostart if needed:

```powershell
.\install-task.ps1
```

## REST API

The REST API is the recommended production interface when another system needs on-demand transcription. It runs as a separate process, keeps the Whisper model loaded, accepts an authorized HTTP request, reads the uploaded audio bytes into memory, and returns the transcription. The API does not persist the uploaded binary file to disk.

Configure the API in `.env` before exposing it:

```text
LOCAL_IP=127.0.0.1
WHISPER_API_HOST=${LOCAL_IP}
WHISPER_API_PORT=18088
WHISPER_API_TOKEN=change-this-token
WHISPER_API_MAX_UPLOAD_BYTES=262144000
```

Use a strong private token. Use `127.0.0.1` for a single-machine install, or set `LOCAL_IP` to the server LAN/VPN IP when the API must be reachable from other machines. Restrict access with Windows Firewall or a reverse proxy. Keep TLS termination outside this service, for example in IIS, nginx, or your ingress layer.

Start the API in the background:

```powershell
cd <install-dir>
.\run-api.ps1
```

Check, stop, or restart the background API process:

```powershell
cd <install-dir>
.\status-api.ps1
.\stop-api.ps1
.\restart-api.ps1
```

Install API autostart with Windows Scheduled Task. The scheduled task runs `api-serve.ps1` in the foreground so Windows can monitor and restart it correctly:

```powershell
cd <install-dir>
.\install-api-task.ps1
```

Built-in status dashboard:

```text
http://127.0.0.1:18088/
```

The root page is a React dashboard with live WebSocket updates from `/ws/status`. It shows loaded model settings, LM Studio configuration, available LM Studio models, runtime LM Studio controls, active jobs, counters, processing totals, and recent request history. The same data is available as JSON:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:18088/status
```

Health check:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:18088/health
```

Create a transcription as JSON. Send the audio file as the raw request body with `Content-Type: application/octet-stream`; do not use `multipart/form-data` if you want to avoid temporary binary files on the server.

```powershell
$headers = @{
  Authorization = "Bearer change-this-token"
  "Content-Type" = "application/octet-stream"
  "X-Filename" = "call.wav"
}

Invoke-RestMethod `
  -Uri "http://127.0.0.1:18088/v1/transcriptions" `
  -Method Post `
  -Headers $headers `
  -InFile "C:\Audio\call.wav"
```

Return plain text:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:18088/v1/transcriptions?response_format=text" `
  -Method Post `
  -Headers $headers `
  -InFile "C:\Audio\call.wav"
```

Return SRT subtitles:

```powershell
curl.exe `
  -H "Authorization: Bearer change-this-token" `
  -H "Content-Type: application/octet-stream" `
  -H "X-Filename: call.wav" `
  --data-binary "@C:\Audio\call.wav" `
  "http://127.0.0.1:18088/v1/transcriptions?response_format=srt"
```

Response formats:

- `json` returns `metadata`, `text`, `segments`, and `srt`.
- `text` returns only the recognized transcript as `text/plain`.
- `srt` returns subtitles as `application/x-subrip`.

Transcription authorization:

- Header: `Authorization: Bearer <WHISPER_API_TOKEN>`
- Missing or invalid token returns `401 Unauthorized`.
- Missing server token returns `503`, so production cannot accidentally run without authentication.

Operational notes:

- `run-api.ps1` starts the API as a background process and writes `api.pid`; use `status-api.ps1` to inspect it, `stop-api.ps1` to stop it, and `restart-api.ps1` to reload it after config or code changes.
- The dashboard is served from `GET /`; live status updates use the `/ws/status` WebSocket, raw JSON is available from `GET /status`, and LM Studio models are exposed by `GET /lm-studio/models`.
- API wrapper logs are written to `logs/api.log`; uvicorn stdout and stderr are written to `logs/api.stdout.log` and `logs/api.stderr.log`.
- If the configured port is already occupied, `run-api.ps1` exits with a clear error instead of leaving a half-started process.
- Requests are serialized with a model lock because one GPU model instance is shared by the API process.
- The maximum request size is controlled by `WHISPER_API_MAX_UPLOAD_BYTES`.
- The uploaded audio bytes are held in process memory only for the duration of the request.
- Generated transcripts are returned to the caller and are not written to `out` by the REST API.

## ffmpeg

System `ffmpeg` is usually not required: `faster-whisper` installs PyAV, which already includes the FFmpeg libraries needed for most formats. If a specific format fails to decode, install FFmpeg:

```powershell
winget install Gyan.FFmpeg
```

## LM Studio

LM Studio is optional and is used only as a second pass to polish the raw Whisper transcript. Whisper output is always returned as `text`; when LM Studio polishing is enabled, API JSON responses also include `polished_text`.

Configure LM Studio in `.env`:

```text
LOCAL_IP=127.0.0.1
LM_STUDIO_ENABLED=false
LM_STUDIO_BASE_URL=http://${LOCAL_IP}:1234/v1
LM_STUDIO_MODEL=local-model
LM_STUDIO_MAX_TOKENS=4096
LM_STUDIO_CHUNK_MAX_CHARS=3500
LM_STUDIO_MODELS_TIMEOUT_SECONDS=15
LM_STUDIO_TOKEN=
LM_STUDIO_PROMPT=Correct obvious speech-recognition errors in the transcript. Preserve the original meaning, speaker intent, names, numbers, dates, technical terms, and structure. Do not add facts, explanations, summaries, or new information. Return only the corrected transcript text.
```

If your LM Studio server requires an API key, set `LM_STUDIO_TOKEN`. The service sends it as:

```text
Authorization: Bearer <LM_STUDIO_TOKEN>
```

You can enable or disable LM Studio polishing at runtime from the built-in status dashboard:

```text
http://127.0.0.1:18088/
```

Use the dashboard to refresh available LM Studio models, select the polishing model, and enable or disable LM Studio polishing. These dashboard controls are intentionally public on the local status page; the `LM_STUDIO_TOKEN` stays only on the server and is never sent to the browser. If LM Studio is slow or unavailable, the dashboard still shows the model from `.env` and reports the connection error as diagnostics. The prompt is read-only in the dashboard and cannot be changed through the public config endpoint. Runtime changes affect only the running API process; update `.env` as well if you want the same settings after restart.

Long transcripts are polished in chunks built from Whisper segments. Tune `LM_STUDIO_CHUNK_MAX_CHARS` for smaller local models; `3500` is a conservative default. `LM_STUDIO_MODELS_TIMEOUT_SECONDS` controls how long the dashboard waits for `/v1/models` before falling back to the configured `.env` model.

## GPU Check

```powershell
.\.venv\Scripts\python.exe -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"
```

If the output contains `float16`, CUDA is available.
