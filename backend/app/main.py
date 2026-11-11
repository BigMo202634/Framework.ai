"""FRAMEWORK AI backend, v0.1.

Run from backend/:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.brain.base import EditRequest
from app.brain.chat import get_chat
from app.brain.mock import MockEditorBrain
from app.config import Settings, get_settings
from app.engine.audio import AudioAnalysis, AudioError, analyze
from app.engine.commands import Command, CommandError, apply
from app.engine.plan import EditPlan
from app.engine.render import render
from app.engine.validate import ValidationResult, validate_plan
from app.jobs import Job, JobStore
from app.media.probe import MediaInfo, ProbeError, probe
from app.media.storage import LocalStorage, MediaNotFound, UploadTooLarge

log = logging.getLogger("framework")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="FRAMEWORK AI", version="0.2.0")

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_storage(settings: Settings = Depends(get_settings)) -> LocalStorage:
    return LocalStorage(settings.storage_dir)


_job_stores: dict[Path, JobStore] = {}


def get_jobs(settings: Settings = Depends(get_settings)) -> JobStore:
    root = Path(settings.storage_dir).resolve() / "_jobs"
    if root not in _job_stores:
        _job_stores[root] = JobStore(root)
    return _job_stores[root]


def get_brain() -> MockEditorBrain:
    # Only the mock brain exists in v0.1. The Claude brain plugs in here behind the same interface.
    return MockEditorBrain()


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


# ---------------------------------------------------------------- milestone 2: auto edit

def _load_info(storage: LocalStorage, media_id: str) -> MediaInfo:
    try:
        return MediaInfo(**storage.load_info(media_id)["info"])
    except MediaNotFound as exc:
        raise HTTPException(404, "Media not found") from exc


def _analysis(storage: LocalStorage, settings: Settings, media_id: str, info: MediaInfo) -> AudioAnalysis | None:
    """Silence analysis, cached in the media folder after the first run."""
    if info.audio is None:
        return None
    cached = storage.load_json(media_id, "analysis.json")
    if cached:
        return AudioAnalysis(**cached)
    try:
        result = analyze(storage.source_path(media_id), info.duration_s, settings.ffmpeg_path)
    except AudioError as exc:
        raise HTTPException(422, str(exc)) from exc
    storage.save_json(media_id, "analysis.json", result.model_dump())
    return result


@app.post("/api/media/{media_id}/analyze", response_model=AudioAnalysis)
def analyze_media(media_id: str, settings: Settings = Depends(get_settings),
                  storage: LocalStorage = Depends(get_storage)) -> AudioAnalysis:
    """Measure loudness and find silences."""
    info = _load_info(storage, media_id)
    result = _analysis(storage, settings, media_id, info)
    if result is None:
        raise HTTPException(422, "This video has no audio track to analyse")
    return result


class PlanResponse(BaseModel):
    plan: EditPlan
    validation: ValidationResult
    source_duration_s: float


@app.post("/api/media/{media_id}/plan", response_model=PlanResponse)
def plan_edit(media_id: str, request: EditRequest = EditRequest(),
              settings: Settings = Depends(get_settings), storage: LocalStorage = Depends(get_storage),
              brain: MockEditorBrain = Depends(get_brain)) -> PlanResponse:
    """Ask the Editor Brain for an edit plan and validate it. Nothing is rendered."""
    info = _load_info(storage, media_id)
    audio = _analysis(storage, settings, media_id, info)
    plan = brain.plan(media_id, info, audio, request)
    validation = validate_plan(plan, info, media_id)
    storage.save_json(media_id, "plan.json", plan.model_dump())
    return PlanResponse(plan=plan, validation=validation, source_duration_s=info.duration_s)


class RenderRequest(BaseModel):
    plan: EditPlan | None = None       # render this exact plan (e.g. after the user tweaks it)
    request: EditRequest = EditRequest()  # or let the brain make one


@app.post("/api/media/{media_id}/render", response_model=Job, status_code=202)
def render_edit(media_id: str, body: RenderRequest = RenderRequest(),
                settings: Settings = Depends(get_settings), storage: LocalStorage = Depends(get_storage),
                jobs: JobStore = Depends(get_jobs), brain: MockEditorBrain = Depends(get_brain)) -> Job:
    """Validate a plan and render it in the background. Poll GET /api/jobs/{job_id} for progress."""
    info = _load_info(storage, media_id)
    plan = body.plan or brain.plan(media_id, info, _analysis(storage, settings, media_id, info), body.request)
    validation = validate_plan(plan, info, media_id)
    if not validation.ok:
        raise HTTPException(422, {"message": "The edit plan is not valid", "errors": validation.errors})
    src = storage.source_path(media_id)
    folder = storage.folder(media_id)

    def work(job: Job, update) -> str:
        name = f"edit_{job.job_id[:8]}.mp4"
        storage.save_json(media_id, f"plan_{job.job_id[:8]}.json", plan.model_dump())
        update(0.0, f"Rendering {len(plan.segments)} cuts")
        # Segments are cached, so after a chat edit only the changed parts are re-rendered.
        render(plan, info, src, folder / name, settings.ffmpeg_path,
               on_progress=lambda p: update(p, f"Rendering {int(p * 100)}%"), cache_dir=folder / "cache")
        return name

    return jobs.submit(media_id, "render", work)


@app.get("/api/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, jobs: JobStore = Depends(get_jobs)) -> Job:
    try:
        return jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


@app.get("/api/media/{media_id}/exports/{name}")
def download_export(media_id: str, name: str, storage: LocalStorage = Depends(get_storage)) -> FileResponse:
    if not (name.startswith("edit_") and name.endswith(".mp4") and "/" not in name and ".." not in name):
        raise HTTPException(404, "Export not found")
    try:
        path = storage.folder(media_id) / name
    except MediaNotFound as exc:
        raise HTTPException(404, "Export not found") from exc
    if not path.is_file():
        raise HTTPException(404, "Export not found")
    return FileResponse(path, media_type="video/mp4", filename=name)


# ---------------------------------------------------------------- timeline chat

class ChatRequest(BaseModel):
    message: str
    plan: EditPlan
    mode: str | None = None  # "rules" forces the free mode even when an API key is set


class ChatResponse(BaseModel):
    reply: str
    changes: list[str]
    commands: list[Command]
    plan: EditPlan
    validation: ValidationResult
    mode: str


@app.post("/api/media/{media_id}/chat", response_model=ChatResponse)
def chat_edit(media_id: str, body: ChatRequest, settings: Settings = Depends(get_settings),
              storage: LocalStorage = Depends(get_storage),
              brain: MockEditorBrain = Depends(get_brain)) -> ChatResponse:
    """Plain-English instruction in, updated (validated) edit plan out. Nothing is rendered."""
    info = _load_info(storage, media_id)
    if body.plan.media_id != media_id:
        raise HTTPException(422, "Plan belongs to a different video")
    chat = get_chat(body.mode, settings.anthropic_api_key)
    try:
        result = chat.interpret(body.message, body.plan)
    except Exception as exc:  # network/API problems shouldn't kill the editor
        log.warning("Chat failed: %s", exc)
        raise HTTPException(502, f"The AI editor is unavailable right now: {exc}") from exc

    def replan(padding_s, keep_pauses_under_s, remove_silences, punch_ins):
        req = EditRequest(aspect=body.plan.output.aspect, punch_ins=punch_ins)
        if padding_s is not None:
            req.padding_s = max(0.0, min(1.0, padding_s))
        if keep_pauses_under_s is not None:
            req.keep_pauses_under_s = max(0.0, min(3.0, keep_pauses_under_s))
        if remove_silences is not None:
            req.remove_silences = remove_silences
        return brain.plan(media_id, info, _analysis(storage, settings, media_id, info), req)

    plan, changes, problems = body.plan, [], []
    for cmd in result.commands:
        try:
            plan, change = apply(plan, cmd, replan)
            changes.append(change)
        except CommandError as exc:
            problems.append(str(exc))
    if changes:
        plan = plan.model_copy(update={"brain": f"{plan.brain.split('+')[0]}+chat"})
    validation = validate_plan(plan, info, media_id)
    if not validation.ok:  # never hand back a plan the renderer would reject
        problems += validation.errors
        plan, changes = body.plan, []
        validation = validate_plan(plan, info, media_id)

    reply = result.reply
    if changes:
        reply = (reply + " " if chat.name == "claude" else "") + "; ".join(changes) + "."
    if problems:
        reply += " " + " ".join(f"Couldn't do that: {p}." for p in problems)
    return ChatResponse(reply=reply.strip(), changes=changes, commands=result.commands, plan=plan,
                        validation=validation, mode=chat.name)
