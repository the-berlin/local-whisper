from __future__ import annotations

import argparse
import sys
import json
import os
import shutil
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import requests

_CUDA_DLL_DIRECTORY_HANDLES = []


def add_cuda_dll_directories() -> None:
    if os.name != "nt":
        return
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    directories = [
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "nvidia" / "cuda_nvrtc" / "bin",
        site_packages / "ctranslate2",
    ]
    existing = [str(directory) for directory in directories if directory.exists()]
    if existing:
        os.environ["PATH"] = os.pathsep.join(existing + [os.environ.get("PATH", "")])
    for directory in existing:
        _CUDA_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(directory))


add_cuda_dll_directories()
from faster_whisper import WhisperModel

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".flac", ".wma", ".webm", ".mkv", ".mov"}


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{timestamp()}] {message}", flush=True)


def safe_name(value: str, fallback: str = "item") -> str:
    cleaned = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in value).strip()
    return cleaned or fallback


def safe_stem(path: Path) -> str:
    return safe_name(path.stem, "audio")


def relative_path(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return Path(path.name)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.with_name(f"{path.name}-{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


def is_file_stable(path: Path, wait_seconds: float = 2.0) -> bool:
    try:
        first = path.stat().st_size
        time.sleep(wait_seconds)
        second = path.stat().st_size
        return first == second and second > 0
    except FileNotFoundError:
        return False


def format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(path: Path, segments: list[dict]) -> None:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        lines.append(str(index))
        lines.append(f"{format_srt_time(segment['start'])} --> {format_srt_time(segment['end'])}")
        lines.append(segment["text"].strip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def polish_with_lm_studio(text: str) -> Optional[str]:
    if not env_bool("LM_STUDIO_ENABLED", False):
        return None
    base_url = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
    model = os.environ.get("LM_STUDIO_MODEL", "local-model")
    prompt = os.environ.get("LM_STUDIO_PROMPT", "Clean up this transcript without changing meaning.")
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.1,
            },
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log(f"LM Studio polishing skipped: {exc}")
        return None


@dataclass(frozen=True)
class Settings:
    root: Path
    inbox: Path
    out: Path
    archive: Path
    failed: Path
    model_name: str
    language: Optional[str]
    device: str
    compute_type: str
    beam_size: int
    vad_filter: bool
    poll_seconds: int
    min_audio_bytes: int

    @staticmethod
    def from_env(root: Path) -> "Settings":
        return Settings(
            root=root,
            inbox=Path(os.environ.get("WHISPER_INBOX", root / "inbox")),
            out=Path(os.environ.get("WHISPER_OUT", root / "out")),
            archive=Path(os.environ.get("WHISPER_ARCHIVE", root / "archive")),
            failed=Path(os.environ.get("WHISPER_FAILED", root / "failed")),
            model_name=os.environ.get("WHISPER_MODEL", "medium"),
            language=os.environ.get("WHISPER_LANGUAGE") or None,
            device=os.environ.get("WHISPER_DEVICE", "auto"),
            compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "auto"),
            beam_size=env_int("WHISPER_BEAM_SIZE", 5),
            vad_filter=env_bool("WHISPER_VAD_FILTER", True),
            poll_seconds=env_int("WHISPER_POLL_SECONDS", 5),
            min_audio_bytes=env_int("WHISPER_MIN_AUDIO_BYTES", 1024),
        )

    def ensure_dirs(self) -> None:
        for directory in [self.inbox, self.out, self.archive, self.failed, self.root / "logs", self.root / "models"]:
            directory.mkdir(parents=True, exist_ok=True)


def find_audio_files(inbox: Path) -> Iterable[Path]:
    paths = [path for path in inbox.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS]
    yield from sorted(paths, key=lambda p: p.stat().st_mtime if p.exists() else 0)


def output_directory(settings: Settings, audio_path: Path) -> Path:
    rel = relative_path(audio_path, settings.inbox)
    safe_parent = Path(*(safe_name(part) for part in rel.parent.parts)) if rel.parent.parts else Path()
    return unique_dir(settings.out / safe_parent / safe_stem(audio_path))


def move_to_bucket(settings: Settings, audio_path: Path, bucket: Path) -> Path:
    rel = relative_path(audio_path, settings.inbox)
    safe_parent = Path(*(safe_name(part) for part in rel.parent.parts)) if rel.parent.parts else Path()
    target = unique_path(bucket / safe_parent / safe_name(audio_path.name, "audio"))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(audio_path), str(target))
    return target


def fail_file(settings: Settings, audio_path: Path, reason: str) -> None:
    target = move_to_bucket(settings, audio_path, settings.failed)
    reason_path = target.with_suffix(target.suffix + ".reason.txt")
    reason_path.write_text(reason + "\n", encoding="utf-8")
    log(f"Moved to failed: {target} ({reason})")


def transcribe_file(model: WhisperModel, settings: Settings, audio_path: Path) -> None:
    rel = relative_path(audio_path, settings.inbox)
    log(f"Transcribing: {rel}")
    job_out = output_directory(settings, audio_path)
    job_out.mkdir(parents=True, exist_ok=False)

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=settings.language,
        beam_size=settings.beam_size,
        vad_filter=settings.vad_filter,
    )
    segments = [
        {"start": item.start, "end": item.end, "text": item.text}
        for item in segments_iter
    ]
    text = "\n".join(segment["text"].strip() for segment in segments if segment["text"].strip()).strip()

    metadata = {
        "source": str(audio_path),
        "relative_source": str(rel),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": settings.model_name,
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "duration_after_vad": getattr(info, "duration_after_vad", None),
        "device": settings.device,
        "compute_type": settings.compute_type,
    }

    (job_out / "transcript.txt").write_text(text + "\n", encoding="utf-8")
    (job_out / "segments.json").write_text(json.dumps({"metadata": metadata, "segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(job_out / "subtitles.srt", segments)

    polished = polish_with_lm_studio(text)
    if polished:
        (job_out / "transcript.polished.txt").write_text(polished + "\n", encoding="utf-8")

    target = move_to_bucket(settings, audio_path, settings.archive)
    log(f"Done: {rel} -> {job_out}; archived as {target}")


def run_once(model: WhisperModel, settings: Settings) -> int:
    count = 0
    for audio_path in find_audio_files(settings.inbox):
        rel = relative_path(audio_path, settings.inbox)
        if not is_file_stable(audio_path):
            log(f"Skipping unstable file: {rel}")
            continue
        if audio_path.stat().st_size < settings.min_audio_bytes:
            fail_file(settings, audio_path, f"File is smaller than WHISPER_MIN_AUDIO_BYTES={settings.min_audio_bytes}")
            continue
        try:
            transcribe_file(model, settings, audio_path)
            count += 1
        except Exception as exc:
            log(f"Failed: {rel}")
            traceback.print_exc()
            try:
                fail_file(settings, audio_path, f"{type(exc).__name__}: {exc}")
            except Exception:
                pass
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Local faster-whisper transcriber for Windows.")
    parser.add_argument("--root", default=os.environ.get("WHISPER_ROOT", str(Path(__file__).resolve().parents[1])))
    parser.add_argument("--mode", choices=["watch", "once"], default="watch")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    load_env_file(root / ".env")
    settings = Settings.from_env(root)
    settings.ensure_dirs()

    log(f"Loading model={settings.model_name}, device={settings.device}, compute_type={settings.compute_type}")
    model = WhisperModel(
        settings.model_name,
        device=settings.device,
        compute_type=settings.compute_type,
        download_root=str(settings.root / "models"),
    )
    log(f"Ready. Inbox: {settings.inbox}")

    if args.mode == "once":
        run_once(model, settings)
        return 0

    while True:
        run_once(model, settings)
        time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("Stopped by user")
        raise SystemExit(0)



