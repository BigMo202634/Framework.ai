"""FRAMEWORK AI backend, v0.1.

Run from backend/:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.brain.base import EditRequest
from app.brain.chat import get_chat
from app.brain.director import CreativeCuts, Direction, creative_cuts, get_director
from app.brain.mock import MockEditorBrain
from app.config import Settings, get_settings
from app.engine.audio import AudioAnalysis, AudioError, analyze
from app.engine.commands import Command, CommandError, apply
from app.engine.captions import FONTS_DIR, CapLine, build_ass, caption_lines
from app.engine.plan import EditPlan, resolve_output
from app.engine.render import render
from app.engine.transcribe import Transcript, TranscribeError, transcribe
from app.engine.validate import ValidationResult, validate_plan
from app.jobs import Job, JobStore
from app.media.probe import MediaInfo, ProbeError, probe
from app.media.preview import WAVEFORM_RATE, PreviewError, make_proxy, waveform
from app.media.storage import LocalStorage, MediaNotFound, UploadTooLarge

log = logging.getLogger("framework")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="FRAMEWORK AI", version="0.6.0")

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


# The caption font, so the editor preview uses exactly the font that gets burned in.
app.mount("/api/fonts", StaticFiles(directory=FONTS_DIR), name="fonts")


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
    if settings.make_proxies:
        # Start the preview copy now, while the first edit is being made, so the editor opens faster.
        threading.Thread(target=_warm_preview, args=(storage, settings, media_id, info), daemon=True).start()
    return _summary(media_id, original_name, info)


def _warm_preview(storage: LocalStorage, settings: Settings, media_id: str, info: MediaInfo) -> None:
    try:
        make_proxy(storage.source_path(media_id), storage.folder(media_id), info, settings.ffmpeg_path)
    except Exception as exc:  # the editor will retry and show the error itself
        log.warning("Preview copy failed for %s: %s", media_id, exc)


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


def _transcript(storage: LocalStorage, settings: Settings, media_id: str, info: MediaInfo) -> Transcript | None:
    """Word-level transcript, cached in the media folder after the first run (it takes ~1 min)."""
    if info.audio is None or not settings.whisper_model:
        return None
    cached = storage.load_json(media_id, "transcript.json")
    if cached and cached.get("model") == settings.whisper_model and cached.get("method") == "phrases":
        return Transcript(**cached)
    audio = _analysis(storage, settings, media_id, info)
    result = transcribe(storage.source_path(media_id), settings.ffmpeg_path, settings.whisper_model,
                        speech=audio.speech if audio else None)
    storage.save_json(media_id, "transcript.json", result.model_dump())
    return result


def _creative(storage: LocalStorage, settings: Settings, media_id: str, info: MediaInfo,
              warnings: list[str], prefer: str | None = None) -> CreativeCuts | None:
    """Transcript + creative director decisions. Cached per director so a replan costs nothing."""
    try:
        transcript = _transcript(storage, settings, media_id, info)
    except TranscribeError as exc:
        log.warning("Transcription failed: %s", exc)
        warnings.append(f"Couldn't transcribe, so fillers and repeats were not cut: {exc}")
        return None
    if transcript is None:
        return None
    director = get_director(prefer, settings.anthropic_api_key)
    name = f"direction_{director.name}.json"
    cached = storage.load_json(media_id, name)
    if cached and cached.get("words") == len(transcript.words):
        direction = Direction(**cached["direction"])
    else:
        try:
            direction = director.direct(transcript)
        except Exception as exc:  # Claude unreachable: the free rules still do the basics
            log.warning("Director failed, using rules: %s", exc)
            warnings.append("The AI director was unavailable, so only the basic rules were used.")
            direction = get_director("rules").direct(transcript)
        storage.save_json(media_id, name, {"words": len(transcript.words), "direction": direction.model_dump()})
    return creative_cuts(transcript, direction, info.duration_s)


@app.get("/api/media/{media_id}/transcript", response_model=Transcript)
def get_transcript(media_id: str, settings: Settings = Depends(get_settings),
                   storage: LocalStorage = Depends(get_storage)) -> Transcript:
    """Word-by-word transcript with timings (made on first request, then cached)."""
    info = _load_info(storage, media_id)
    try:
        result = _transcript(storage, settings, media_id, info)
    except TranscribeError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(422, "This video has no audio track to transcribe")
    return result


# ---------------------------------------------------------------- editor media

@app.get("/api/media/{media_id}/proxy.mp4")
def get_proxy(media_id: str, settings: Settings = Depends(get_settings),
              storage: LocalStorage = Depends(get_storage)) -> FileResponse:
    """Small H.264 copy of the source for previewing and scrubbing (made on first request)."""
    info = _load_info(storage, media_id)
    try:
        path = make_proxy(storage.source_path(media_id), storage.folder(media_id), info, settings.ffmpeg_path)
    except PreviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return FileResponse(path, media_type="video/mp4")


class Waveform(BaseModel):
    rate: int
    peaks: list[int]


@app.get("/api/media/{media_id}/waveform", response_model=Waveform)
def get_waveform(media_id: str, settings: Settings = Depends(get_settings),
                 storage: LocalStorage = Depends(get_storage)) -> Waveform:
    """Audio peaks (0-100), WAVEFORM_RATE per second of source, for drawing the timeline."""
    info = _load_info(storage, media_id)
    if info.audio is None:
        return Waveform(rate=WAVEFORM_RATE, peaks=[])
    cached = storage.load_json(media_id, "waveform.json")
    if cached and cached.get("rate") == WAVEFORM_RATE:
        return Waveform(**cached)
    try:
        result = Waveform(rate=WAVEFORM_RATE, peaks=waveform(storage.source_path(media_id), settings.ffmpeg_path))
    except PreviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    storage.save_json(media_id, "waveform.json", result.model_dump())
    return result


class CaptionsRequest(BaseModel):
    plan: EditPlan


@app.post("/api/media/{media_id}/captions", response_model=list[CapLine])
def preview_captions(media_id: str, body: CaptionsRequest, settings: Settings = Depends(get_settings),
                     storage: LocalStorage = Depends(get_storage)) -> list[CapLine]:
    """Caption lines for a plan, in edited-timeline seconds, so the editor can preview them."""
    info = _load_info(storage, media_id)
    try:
        transcript = _transcript(storage, settings, media_id, info)
    except TranscribeError as exc:
        raise HTTPException(422, str(exc)) from exc
    if transcript is None:
        raise HTTPException(422, "Captions need speech: this video has no audio, or transcription is off")
    return caption_lines(transcript, body.plan)


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
    warnings: list[str] = []
    creative = _creative(storage, settings, media_id, info, warnings) if request.creative_cuts else None
    plan = brain.plan(media_id, info, audio, request, creative)
    validation = validate_plan(plan, info, media_id)
    validation.warnings = warnings + validation.warnings
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
    plan = body.plan
    if plan is None:
        creative = _creative(storage, settings, media_id, info, []) if body.request.creative_cuts else None
        plan = brain.plan(media_id, info, _analysis(storage, settings, media_id, info), body.request, creative)
    validation = validate_plan(plan, info, media_id)
    if not validation.ok:
        raise HTTPException(422, {"message": "The edit plan is not valid", "errors": validation.errors})
    src = storage.source_path(media_id)
    folder = storage.folder(media_id)

    def work(job: Job, update) -> str:
        name = f"edit_{job.job_id[:8]}.mp4"
        storage.save_json(media_id, f"plan_{job.job_id[:8]}.json", plan.model_dump())
        ass = None
        if plan.captions.enabled:
            update(0.0, "Reading your words for the captions")
            transcript = _transcript(storage, settings, media_id, info)
            if transcript is not None:
                out = resolve_output(plan.output, info)
                ass = build_ass(caption_lines(transcript, plan), plan.captions, out.width, out.height)
        update(0.0, f"Rendering {len(plan.segments)} cuts")
        # Segments are cached, so after a chat edit only the changed parts are re-rendered.
        render(plan, info, src, folder / name, settings.ffmpeg_path,
               on_progress=lambda p: update(p, "Adding captions" if p > 0.955 else f"Rendering {int(p * 100)}%"),
               cache_dir=folder / "cache", captions_ass=ass)
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

    def replan(cmd: Command, punch_ins: bool):
        # Keep the creative cuts the current plan has unless the command changes that.
        had_creative = bool(body.plan.removed)
        req = EditRequest(aspect=body.plan.output.aspect, punch_ins=punch_ins,
                          creative_cuts=had_creative if cmd.creative_cuts is None else cmd.creative_cuts)
        if cmd.padding_s is not None:
            req.padding_s = max(0.0, min(1.0, cmd.padding_s))
        if cmd.keep_pauses_under_s is not None:
            req.keep_pauses_under_s = max(0.0, min(3.0, cmd.keep_pauses_under_s))
        if cmd.remove_silences is not None:
            req.remove_silences = cmd.remove_silences
        creative = _creative(storage, settings, media_id, info, []) if req.creative_cuts else None
        return brain.plan(media_id, info, _analysis(storage, settings, media_id, info), req, creative)

    plan, changes, problems = body.plan, [], []
    for cmd in result.commands:
        try:
            plan, change = apply(plan, cmd, replan)
            changes.append(change)
        except CommandError as exc:
            problems.append(str(exc))
    if changes:
        plan = plan.model_copy(update={"brain": f"{plan.brain.removesuffix('+chat')}+chat"})
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
