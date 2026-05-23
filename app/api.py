from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from transcriber import Settings, WhisperModel, load_env_file, log, transcribe_bytes

ROOT = Path(os.environ.get("WHISPER_ROOT", Path(__file__).resolve().parents[1])).resolve()
load_env_file(ROOT / ".env")
SETTINGS = Settings.from_env(ROOT)
API_TOKEN = os.environ.get("WHISPER_API_TOKEN", "")
MAX_UPLOAD_BYTES = int(os.environ.get("WHISPER_API_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))

app = FastAPI(title="Local Whisper Transcriber", version="1.0")
model_lock = threading.Lock()
model: WhisperModel | None = None


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


@app.on_event("startup")
def load_model() -> None:
    global model
    log(f"API loading model={SETTINGS.model_name}, device={SETTINGS.device}, compute_type={SETTINGS.compute_type}")
    model = WhisperModel(
        SETTINGS.model_name,
        device=SETTINGS.device,
        compute_type=SETTINGS.compute_type,
        download_root=str(SETTINGS.root / "models"),
    )
    log("API ready")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": model is not None}


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
    with model_lock:
        result = transcribe_bytes(model, SETTINGS, audio, source_name)

    if response_format.lower() == "text":
        return PlainTextResponse(result["text"] + "\n")
    if response_format.lower() == "srt":
        return PlainTextResponse(result["srt"], media_type="application/x-subrip")
    return result
