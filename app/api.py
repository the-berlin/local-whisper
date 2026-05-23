from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse

from transcriber import Settings, WhisperModel, env_bool, load_env_file, log, transcribe_bytes

ROOT = Path(os.environ.get("WHISPER_ROOT", Path(__file__).resolve().parents[1])).resolve()
load_env_file(ROOT / ".env")
SETTINGS = Settings.from_env(ROOT)
API_TOKEN = os.environ.get("WHISPER_API_TOKEN", "")
MAX_UPLOAD_BYTES = int(os.environ.get("WHISPER_API_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
STARTED_AT = datetime.now().isoformat(timespec="seconds")

app = FastAPI(title="Local Whisper Transcriber", version="1.0")
model_lock = threading.Lock()
telemetry_lock = threading.Lock()
model: WhisperModel | None = None
model_loaded_at: str | None = None
request_history: deque[dict[str, Any]] = deque(maxlen=100)
active_jobs: dict[str, dict[str, Any]] = {}
stats: dict[str, Any] = {
    "total_requests": 0,
    "completed_requests": 0,
    "failed_requests": 0,
    "total_bytes": 0,
    "total_audio_seconds": 0.0,
    "total_processing_seconds": 0.0,
}

STATUS_PAGE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Local Whisper Status</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0d10;
      --panel: #14181d;
      --panel-2: #101419;
      --line: #27313a;
      --text: #eef3f7;
      --muted: #9aa8b5;
      --soft: #c9d3dc;
      --green: #54d18a;
      --red: #ff6b6b;
      --amber: #f2bf5e;
      --blue: #7db7ff;
      --chip: #202832;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      letter-spacing: 0;
    }
    main { max-width: 1480px; margin: 0 auto; padding: 24px; }
    header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
    h1 { margin: 0; font-size: 28px; font-weight: 650; }
    h2 { margin: 0 0 12px; font-size: 15px; font-weight: 650; color: var(--soft); }
    .sub { color: var(--muted); margin-top: 4px; font-size: 13px; }
    .status { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; white-space: nowrap; }
    .dot { width: 9px; height: 9px; border-radius: 999px; background: var(--red); box-shadow: 0 0 18px currentColor; }
    .dot.ok { background: var(--green); }
    .dot.warn { background: var(--amber); }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
    .panel { border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 14px; min-width: 0; }
    .metric .label { color: var(--muted); font-size: 12px; }
    .metric .value { margin-top: 5px; font-size: 24px; font-weight: 680; }
    .wide { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.9fr); gap: 12px; margin-bottom: 12px; }
    .kv { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 7px 12px; font-size: 12px; }
    .kv div:nth-child(odd) { color: var(--muted); }
    .kv div:nth-child(even) { color: var(--soft); overflow-wrap: anywhere; }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip { background: var(--chip); border: 1px solid var(--line); border-radius: 999px; color: var(--soft); padding: 5px 9px; font-size: 12px; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12px; }
    th, td { padding: 8px 7px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; overflow: hidden; text-overflow: ellipsis; }
    th { color: var(--muted); font-weight: 600; background: var(--panel-2); position: sticky; top: 0; }
    td { color: var(--soft); }
    .oktext { color: var(--green); }
    .errtext { color: var(--red); }
    .pending { color: var(--amber); }
    .mono { font-family: Consolas, "Cascadia Mono", ui-monospace, monospace; }
    .small { font-size: 11px; color: var(--muted); }
    .scroll { max-height: 430px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--soft); font-size: 11px; font-family: Consolas, "Cascadia Mono", ui-monospace, monospace; }
    @media (max-width: 980px) {
      main { padding: 16px; }
      header, .wide { grid-template-columns: 1fr; display: grid; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kv { grid-template-columns: 120px minmax(0, 1fr); }
    }
  </style>
</head>
<body>
  <main id="root"></main>
  <script>
    const { useEffect, useMemo, useState } = React;
    const e = React.createElement;
    const fmt = (value, digits = 1) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits });
    const bytes = (value) => {
      const n = Number(value || 0);
      if (n >= 1024 * 1024 * 1024) return fmt(n / 1024 / 1024 / 1024, 2) + ' GB';
      if (n >= 1024 * 1024) return fmt(n / 1024 / 1024, 2) + ' MB';
      if (n >= 1024) return fmt(n / 1024, 1) + ' KB';
      return n + ' B';
    };
    function Metric({ label, value, tone }) {
      return e('section', { className: 'panel metric' },
        e('div', { className: 'label' }, label),
        e('div', { className: 'value ' + (tone || '') }, value)
      );
    }
    function App() {
      const [data, setData] = useState(null);
      const [connected, setConnected] = useState(false);
      useEffect(() => {
        let closed = false;
        let ws;
        const connect = () => {
          ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/status');
          ws.onopen = () => setConnected(true);
          ws.onclose = () => { setConnected(false); if (!closed) setTimeout(connect, 1500); };
          ws.onerror = () => setConnected(false);
          ws.onmessage = (event) => setData(JSON.parse(event.data));
        };
        connect();
        return () => { closed = true; if (ws) ws.close(); };
      }, []);
      const s = data || {};
      const config = s.config || {};
      const stats = s.stats || {};
      const active = s.active_jobs || [];
      const history = s.history || [];
      const lm = config.lm_studio || {};
      const avg = stats.completed_requests ? stats.total_processing_seconds / stats.completed_requests : 0;
      return e(React.Fragment, null,
        e('header', null,
          e('div', null, e('h1', null, 'Local Whisper Transcriber'), e('div', { className: 'sub' }, 'Runtime status, request history, model configuration, and live queue activity')),
          e('div', { className: 'status' }, e('span', { className: 'dot ' + (connected ? 'ok' : 'warn') }), e('span', null, connected ? 'Live WebSocket connected' : 'Waiting for live updates'))
        ),
        e('div', { className: 'grid' },
          e(Metric, { label: 'Total requests', value: fmt(stats.total_requests, 0) }),
          e(Metric, { label: 'Completed', value: fmt(stats.completed_requests, 0), tone: 'oktext' }),
          e(Metric, { label: 'Failed', value: fmt(stats.failed_requests, 0), tone: stats.failed_requests ? 'errtext' : '' }),
          e(Metric, { label: 'Active jobs', value: fmt(active.length, 0), tone: active.length ? 'pending' : '' })
        ),
        e('div', { className: 'grid' },
          e(Metric, { label: 'Total upload volume', value: bytes(stats.total_bytes) }),
          e(Metric, { label: 'Audio processed', value: fmt(stats.total_audio_seconds / 60, 1) + ' min' }),
          e(Metric, { label: 'Processing time', value: fmt(stats.total_processing_seconds / 60, 1) + ' min' }),
          e(Metric, { label: 'Average request', value: fmt(avg, 2) + ' sec' })
        ),
        e('div', { className: 'wide' },
          e('section', { className: 'panel' },
            e('h2', null, 'Model and Runtime'),
            e('div', { className: 'kv' },
              e('div', null, 'Service started'), e('div', null, s.started_at || '-'),
              e('div', null, 'Model loaded'), e('div', null, s.model_loaded_at || '-'),
              e('div', null, 'Model'), e('div', null, config.model_name || '-'),
              e('div', null, 'Language'), e('div', null, config.language || 'auto'),
              e('div', null, 'Device'), e('div', null, config.device || '-'),
              e('div', null, 'Compute type'), e('div', null, config.compute_type || '-'),
              e('div', null, 'Beam size'), e('div', null, config.beam_size || '-'),
              e('div', null, 'VAD filter'), e('div', null, String(config.vad_filter)),
              e('div', null, 'Max upload'), e('div', null, bytes(config.max_upload_bytes)),
              e('div', null, 'Root'), e('div', { className: 'mono small' }, config.root || '-')
            )
          ),
          e('section', { className: 'panel' },
            e('h2', null, 'LM Studio and API'),
            e('div', { className: 'chips' },
              e('span', { className: 'chip' }, 'API auth: ' + (config.api_token_configured ? 'configured' : 'missing')),
              e('span', { className: 'chip' }, 'LM Studio: ' + (lm.enabled ? 'enabled' : 'disabled')),
              e('span', { className: 'chip' }, 'Endpoint: ' + (lm.base_url || '-')),
              e('span', { className: 'chip' }, 'LM model: ' + (lm.model || '-'))
            ),
            e('div', { style: { marginTop: '14px' } }, e('div', { className: 'small', style: { marginBottom: '6px' } }, 'LM Studio prompt'), e('pre', null, lm.prompt || '-'))
          )
        ),
        e('section', { className: 'panel', style: { marginBottom: '12px' } },
          e('h2', null, 'Active Jobs'),
          active.length ? e('div', { className: 'scroll' }, e('table', null,
            e('thead', null, e('tr', null, ['ID','Started','Source','Bytes','Format'].map(h => e('th', { key: h }, h)))),
            e('tbody', null, active.map(j => e('tr', { key: j.id },
              e('td', { className: 'mono' }, j.id), e('td', null, j.started_at), e('td', null, j.source), e('td', null, bytes(j.bytes)), e('td', null, j.response_format)
            )))
          )) : e('div', { className: 'small' }, 'No active jobs.')
        ),
        e('section', { className: 'panel' },
          e('h2', null, 'Recent Requests'),
          e('div', { className: 'scroll' }, e('table', null,
            e('thead', null, e('tr', null, ['Status','Started','Source','Bytes','Audio','Processing','Segments','Chars','Error'].map(h => e('th', { key: h }, h)))),
            e('tbody', null, history.map(j => e('tr', { key: j.id },
              e('td', { className: j.status === 'completed' ? 'oktext' : 'errtext' }, j.status),
              e('td', null, j.started_at),
              e('td', { title: j.source }, j.source),
              e('td', null, bytes(j.bytes)),
              e('td', null, fmt(j.audio_seconds, 1) + 's'),
              e('td', null, fmt(j.processing_seconds, 2) + 's'),
              e('td', null, fmt(j.segment_count, 0)),
              e('td', null, fmt(j.text_chars, 0)),
              e('td', { className: 'errtext', title: j.error || '' }, j.error || '')
            )))
          ))
        )
      );
    }
    ReactDOM.createRoot(document.getElementById('root')).render(e(App));
  </script>
</body>
</html>'''


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="WHISPER_API_TOKEN is not configured")
    expected = f"Bearer {API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def read_body_in_memory(request: Request) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Upload is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def current_snapshot() -> dict[str, Any]:
    with telemetry_lock:
        return {
            "service": "Local Whisper Transcriber",
            "started_at": STARTED_AT,
            "model_loaded": model is not None,
            "model_loaded_at": model_loaded_at,
            "config": {
                "root": str(ROOT),
                "model_name": SETTINGS.model_name,
                "language": SETTINGS.language,
                "device": SETTINGS.device,
                "compute_type": SETTINGS.compute_type,
                "beam_size": SETTINGS.beam_size,
                "vad_filter": SETTINGS.vad_filter,
                "min_audio_bytes": SETTINGS.min_audio_bytes,
                "max_upload_bytes": MAX_UPLOAD_BYTES,
                "api_token_configured": bool(API_TOKEN),
                "lm_studio": {
                    "enabled": env_bool("LM_STUDIO_ENABLED", False),
                    "base_url": os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
                    "model": os.environ.get("LM_STUDIO_MODEL", "local-model"),
                    "prompt": os.environ.get("LM_STUDIO_PROMPT", "Clean up this transcript without changing meaning."),
                },
            },
            "stats": dict(stats),
            "active_jobs": list(active_jobs.values()),
            "history": list(request_history),
        }


def start_job(source_name: str, size: int, response_format: str) -> dict[str, Any]:
    job = {
        "id": f"req-{int(time.time() * 1000)}-{threading.get_ident()}",
        "source": source_name,
        "bytes": size,
        "response_format": response_format,
        "started_at": now_iso(),
        "status": "running",
    }
    with telemetry_lock:
        stats["total_requests"] += 1
        stats["total_bytes"] += size
        active_jobs[job["id"]] = dict(job)
    return job


def finish_job(job: dict[str, Any], status: str, started_perf: float, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    processing_seconds = time.perf_counter() - started_perf
    info = dict(job)
    info.update(
        {
            "status": status,
            "finished_at": now_iso(),
            "processing_seconds": round(processing_seconds, 3),
            "audio_seconds": None,
            "segment_count": 0,
            "text_chars": 0,
            "detected_language": None,
            "error": error,
        }
    )
    if result:
        metadata = result.get("metadata", {})
        info["audio_seconds"] = metadata.get("duration")
        info["detected_language"] = metadata.get("language")
        info["segment_count"] = len(result.get("segments", []))
        info["text_chars"] = len(result.get("text", ""))
    with telemetry_lock:
        active_jobs.pop(job["id"], None)
        if status == "completed":
            stats["completed_requests"] += 1
            stats["total_processing_seconds"] += processing_seconds
            if info["audio_seconds"]:
                stats["total_audio_seconds"] += float(info["audio_seconds"])
        else:
            stats["failed_requests"] += 1
        request_history.appendleft(info)


@app.on_event("startup")
def load_model() -> None:
    global model, model_loaded_at
    log(f"API loading model={SETTINGS.model_name}, device={SETTINGS.device}, compute_type={SETTINGS.compute_type}")
    model = WhisperModel(
        SETTINGS.model_name,
        device=SETTINGS.device,
        compute_type=SETTINGS.compute_type,
        download_root=str(SETTINGS.root / "models"),
    )
    model_loaded_at = now_iso()
    log("API ready")


@app.get("/", response_class=HTMLResponse)
def status_page() -> HTMLResponse:
    return HTMLResponse(STATUS_PAGE)


@app.websocket("/ws/status")
async def status_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(current_snapshot())
            await asyncio_sleep(2)
    except WebSocketDisconnect:
        return


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": model is not None}


@app.get("/status")
def status_json() -> dict[str, Any]:
    return current_snapshot()


@app.post("/v1/transcriptions", dependencies=[Depends(require_token)])
async def create_transcription(
    request: Request,
    x_filename: Annotated[str | None, Header()] = None,
    response_format: str = "json",
):
    if model is None:
        raise HTTPException(status_code=503, detail="Model is not loaded")
    audio = await read_body_in_memory(request)
    if not audio:
        raise HTTPException(status_code=400, detail="Empty request body")
    if len(audio) < SETTINGS.min_audio_bytes:
        raise HTTPException(status_code=400, detail=f"File is smaller than WHISPER_MIN_AUDIO_BYTES={SETTINGS.min_audio_bytes}")

    source_name = x_filename or "request-body"
    job = start_job(source_name, len(audio), response_format)
    started_perf = time.perf_counter()
    try:
        with model_lock:
            result = transcribe_bytes(model, SETTINGS, audio, source_name)
        finish_job(job, "completed", started_perf, result=result)
    except Exception as exc:
        finish_job(job, "failed", started_perf, error=f"{type(exc).__name__}: {exc}")
        raise

    if response_format.lower() == "text":
        return PlainTextResponse(result["text"] + "\n")
    if response_format.lower() == "srt":
        return PlainTextResponse(result["srt"], media_type="application/x-subrip")
    return result
