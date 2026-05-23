# Local Whisper Transcriber

Автономный локальный транскрибатор для Windows 11 Pro / Windows Server 2022 + NVIDIA GPU. Использует `faster-whisper`, CUDA через `ctranslate2`, и хранит модели локально в `models`.

## Быстрый запуск

```powershell
cd S:\development\source\whisper
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
cd S:\development\source\whisper
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
