"""FRAMEWORK AI backend, v0.1.

Run from backend/:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.media.probe import MediaInfo, ProbeError, probe
from app.media.storage import LocalStorage, MediaNotFound, UploadTooLarge

log = logging.getLogger("framework")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="FRAMEWORK AI", version="0.1.0")

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_storage(settings: Settings = Depends(get_settings)) -> LocalStorage:
    return LocalStorage(settings.storage_dir)


class MediaSummary(BaseModel):
    media_id: str
    original_name: str
    duration_s: float
    width: int
    height: int
    fps: float
    orientation: str
    has_audio: bool
    info: MediaInfo


def _summary(media_id: str, original_name: str, info: MediaInfo) -> MediaSummary:
    return MediaSummary(
        media_id=media_id,
        original_name=original_name,
        duration_s=info.duration_s,
        width=info.display_width,
        height=info.display_height,
        fps=info.video.fps if info.video else 0.0,
        orientation=info.orientation,
        has_audio=info.audio is not None,
        info=info,
    )


@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Reports whether FFmpeg/FFprobe are installed, so setup problems show up immediately."""
    return {
        "status": "ok",
        "version": app.version,
        "ffprobe": shutil.which(settings.ffprobe_path) is not None,
        "ffmpeg": shutil.which(settings.ffmpeg_path) is not None,
    }


@app.post("/api/media", response_model=MediaSummary, status_code=201)
def import_media(
    file: UploadFile,
    settings: Settings = Depends(get_settings),
    storage: LocalStorage = Depends(get_storage),
) -> MediaSummary:
    """Import a video: save it, inspect it with FFprobe, and return its technical metadata."""
    original_name = Path(file.filename or "upload").name
    ext = Path(original_name).suffix.lower()
    if ext not in settings.allowed_extensions:
        allowed = ", ".join(sorted(settings.allowed_extensions))
        raise HTTPException(415, f"'{ext or 'no extension'}' is not supported. Use one of: {allowed}")

    try:
        media_id, path = storage.save_upload(file.file, ext, settings.max_upload_bytes)
    except UploadTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc

    try:
        info = probe(path, settings.ffprobe_path)
    except ProbeError as exc:
        storage.delete(media_id)
        log.warning("Import rejected for %s: %s", original_name, exc)
        raise HTTPException(422, str(exc)) from exc

    storage.save_info(media_id, info, original_name)
    log.info("Imported %s as %s (%.1fs, %dx%d)", original_name, media_id, info.duration_s,
             info.display_width, info.display_height)
    return _summary(media_id, original_name, info)


@app.get("/api/media/{media_id}", response_model=MediaSummary)
def get_media(media_id: str, storage: LocalStorage = Depends(get_storage)) -> MediaSummary:
    try:
        data = storage.load_info(media_id)
    except MediaNotFound as exc:
        raise HTTPException(404, "Media not found") from exc
    return _summary(media_id, data["original_name"], MediaInfo(**data["info"]))


@app.delete("/api/media/{media_id}", status_code=204, response_class=Response)
def delete_media(media_id: str, storage: LocalStorage = Depends(get_storage)) -> Response:
    try:
        storage.delete(media_id)
    except MediaNotFound as exc:
        raise HTTPException(404, "Media not found") from exc
    return Response(status_code=204)
