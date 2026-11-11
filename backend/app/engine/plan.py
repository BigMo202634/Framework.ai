"""The edit plan: the contract between the Editor Brain (AI or mock) and the renderer.

The brain may only *describe* an edit in this format. The validator checks it against the real
media before anything is rendered, so a bad AI answer becomes a clear error, not a broken video.
Captions, music, SFX and transitions will be added to this schema in later milestones.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.media.probe import MediaInfo

Aspect = Literal["source", "9:16", "16:9", "1:1", "4:5"]

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


class Segment(BaseModel):
    """One piece of the source placed on the timeline, in order."""

    src_in: float = Field(ge=0, description="Source start time in seconds")
    src_out: float = Field(gt=0, description="Source end time in seconds")
    zoom: float = Field(1.0, description="Punch-in factor. 1.0 = no zoom, 1.2 = 20% closer")
    # Where the zoom/crop is centred, as fractions of the frame (0.5, 0.5 = centre).
    focus_x: float = Field(0.5, ge=0, le=1)
    focus_y: float = Field(0.4, ge=0, le=1)  # slightly above centre: faces sit in the upper half
    reason: str = ""

    @property
    def duration(self) -> float:
        return self.src_out - self.src_in


class OutputSettings(BaseModel):
    aspect: Aspect = "source"
    width: int | None = None   # filled in by resolve_output()
    height: int | None = None
    fps: float | None = None
    crf: int = Field(20, ge=14, le=32)
    audio_bitrate_k: int = 192


class RemovedPart(BaseModel):
    """Something the creative director cut, in source time, so the user can see and question it."""
    start: float
    end: float
    kind: str  # filler | stutter | retake | repetition | off_message
    text: str
    reason: str = ""


class EditPlan(BaseModel):
    version: Literal["0.1"] = "0.1"
    media_id: str
    brain: str = "mock"
    summary: str = ""
    message: str = ""  # what the creator is trying to say, as the director understood it
    segments: list[Segment]
    removed: list[RemovedPart] = []
    output: OutputSettings = OutputSettings()

    @property
    def duration(self) -> float:
        return round(sum(s.duration for s in self.segments), 3)


def _even(n: float) -> int:
    n = int(round(n))
    return n - (n % 2)


def resolve_output(output: OutputSettings, info: MediaInfo) -> OutputSettings:
    """Fill in width/height/fps. 'source' keeps the source size (capped at 1080p on the short side)."""
    out = output.model_copy()
    if out.width is None or out.height is None:
        if out.aspect == "source":
            w, h = info.display_width, info.display_height
            short = min(w, h)
            if short > 1080:
                scale = 1080 / short
                w, h = w * scale, h * scale
            out.width, out.height = _even(w), _even(h)
        else:
            out.width, out.height = ASPECT_SIZES[out.aspect]
    if out.fps is None:
        src_fps = info.video.fps if info.video else 30.0
        out.fps = src_fps if 0 < src_fps <= 60 else 30.0
    return out
