# Local Whisper Transcriber

Автономный локальный транскрибатор для Windows 11 Pro / Windows Server 2022 + NVIDIA GPU. Использует `faster-whisper`, CUDA через `ctranslate2`, и хранит модели локально в `models`.

## Быстрый запуск

```powershell
cd <install-dir>
.\install.ps1
.\run-watch.ps1
```

Кладите аудио/видео файлы в `inbox`. Можно складывать пачками в подпапки, например `inbox\12`; структура подпапок сохранится в `out`, `archive` и `failed`.

Результаты появляются в `out\<подпапка>\<имя файла>`:

- `transcript.txt` - обычный текст
- `subtitles.srt` - субтитры
- `segments.json` - сегменты с таймкодами и метаданными
- `transcript.polished.txt` - появляется только если включена вычитка через LM Studio

После успешной обработки исходный файл переносится в `archive`. При ошибке - в `failed`, рядом создается файл причины `*.reason.txt`.

## Профили GPU

Локальный `.env` не хранится в git. После клонирования скопируйте подходящий пример:

```powershell
Copy-Item .env.rtx3090.example .env
```

Для RTX 3090 24GB профиль использует:

```text
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
```

Для RTX 4060 8GB используйте `.env.rtx4060.example`; там `int8_float16`, чтобы `large-v3` надежнее помещалась в VRAM.

## Автозапуск как служба-процесс

На Windows надежнее запускать этот watcher через Scheduled Task, потому что обычный Python-скрипт не является SCM-службой.

```powershell
cd <install-dir>
.\install-task.ps1
```

Управление:

```powershell
.\status-task.ps1
.\start-task.ps1
.\stop-task.ps1
.\uninstall-task.ps1
```

Задача называется `LocalWhisperTranscriber` и запускает `run-watch.ps1` при старте Windows.

## Перенос на Windows Server 2022 + RTX 3090

1. Установите свежий NVIDIA Driver для RTX 3090.
2. Установите Python 3.12 x64 и включите Python Launcher `py`.
3. Склонируйте репозиторий в нужную папку.
4. Скопируйте профиль:

```powershell
Copy-Item .env.rtx3090.example .env
```

5. Проверьте пути в `.env`.
6. Установите зависимости:

```powershell
.\install.ps1
```

7. Прогрейте модель:

```powershell
.\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16', download_root=r'.\models'); print('ok')"
```

8. Включите автозапуск:

```powershell
.\install-task.ps1
```


## REST API

The REST API is the recommended production interface when another system needs on-demand transcription. It runs as a separate process, keeps the Whisper model loaded, accepts an authorized HTTP request, reads the uploaded audio bytes into memory, and returns the transcription. The API does not persist the uploaded binary file to disk.

Configure the API in `.env` before exposing it:

```text
WHISPER_API_HOST=127.0.0.1
WHISPER_API_PORT=8088
WHISPER_API_TOKEN=change-this-token
WHISPER_API_MAX_UPLOAD_BYTES=262144000
```

Use a strong private token. If the API must be reachable from other machines, set `WHISPER_API_HOST=0.0.0.0` and restrict access with Windows Firewall or a reverse proxy. Keep TLS termination outside this service, for example in IIS, nginx, or your ingress layer.

Start the API in the background:

```powershell
cd <install-dir>
.\run-api.ps1
```

Check or stop the background API process:

```powershell
cd <install-dir>
.\install-api-task.ps1
```

Install API autostart with Windows Scheduled Task. The scheduled task runs `api-serve.ps1` in the foreground so Windows can monitor and restart it correctly:

```powershell
cd <install-dir>
.\install-api-task.ps1
```
Built-in status dashboard:

```text
http://127.0.0.1:8088/
```

The root page is a React dashboard with live WebSocket updates from `/ws/status`. It shows loaded model settings, LM Studio configuration, active jobs, counters, processing totals, and recent request history. The same data is available as JSON:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8088/status
```

Health check:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8088/health
```
Create a transcription as JSON. Send the audio file as the raw request body with `Content-Type: application/octet-stream`; do not use `multipart/form-data` if you want to avoid temporary binary files on the server.

```powershell
$headers = @{
  Authorization = "Bearer change-this-token"
  "Content-Type" = "application/octet-stream"
  "X-Filename" = "call.wav"
}

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8088/v1/transcriptions" `
  -Method Post `
  -Headers $headers `
  -InFile "C:\Audio\call.wav"
```

Return plain text:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8088/v1/transcriptions?response_format=text" `
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
  "http://127.0.0.1:8088/v1/transcriptions?response_format=srt"
```

Response formats:

- `json` returns `metadata`, `text`, `segments`, and `srt`.
- `text` returns only the recognized transcript as `text/plain`.
- `srt` returns subtitles as `application/x-subrip`.

Authorization:

- Header: `Authorization: Bearer <WHISPER_API_TOKEN>`
- Missing or invalid token returns `401 Unauthorized`.
- Missing server token returns `503`, so production cannot accidentally run without authentication.

Operational notes:

- `run-api.ps1` starts the API as a background process and writes `api.pid`; use `status-api.ps1` to inspect it and `stop-api.ps1` to stop it.
- The dashboard is served from `GET /`; live status updates use the `/ws/status` WebSocket, and raw JSON is available from `GET /status`.
- API wrapper logs are written to `logs/api.log`; uvicorn stdout and stderr are written to `logs/api.stdout.log` and `logs/api.stderr.log`.
- If the configured port is already occupied, `run-api.ps1` exits with a clear error instead of leaving a half-started process.
- Requests are serialized with a model lock because one GPU model instance is shared by the API process.
- The maximum request size is controlled by `WHISPER_API_MAX_UPLOAD_BYTES`.
- The uploaded audio bytes are held in process memory only for the duration of the request.
- Generated transcripts are returned to the caller and are not written to `out` by the REST API.
## ffmpeg

Системный `ffmpeg` не обязателен: `faster-whisper` ставит PyAV, который уже содержит нужные FFmpeg-библиотеки для большинства форматов. Если конкретный формат не прочитается, тогда установите:

```powershell
winget install Gyan.FFmpeg
```

## LM Studio

LM Studio не нужен для распознавания. Его можно включить как второй этап для аккуратной вычитки текста:

1. В LM Studio запустите Local Server на `http://127.0.0.1:1234/v1`.
2. В `.env` установите:

```text
LM_STUDIO_ENABLED=true
LM_STUDIO_MODEL=имя-модели-в-LM-Studio
```

Транскрипт Whisper останется неизменным в `transcript.txt`, а вычитанный текст появится в `transcript.polished.txt`.

## Проверка GPU

```powershell
.\.venv\Scripts\python.exe -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"
```

Если вывод содержит `float16`, CUDA доступна.


