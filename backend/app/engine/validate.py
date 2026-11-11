"""Deterministic checks on an edit plan before rendering. No AI involved."""

from __future__ import annotations

from pydantic import BaseModel

from app.engine.plan import EditPlan
from app.media.probe import MediaInfo

MIN_SEGMENT_S = 0.2
MAX_ZOOM = 2.0
MAX_SEGMENTS = 2000


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []


def validate_plan(plan: EditPlan, info: MediaInfo, media_id: str | None = None) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    duration = info.duration_s

    if media_id is not None and plan.media_id != media_id:
        errors.append(f"Plan is for media {plan.media_id}, not {media_id}")
    if not plan.segments:
        errors.append("Plan has no segments")
    if len(plan.segments) > MAX_SEGMENTS:
        errors.append(f"Plan has {len(plan.segments)} segments; the limit is {MAX_SEGMENTS}")

    for i, s in enumerate(plan.segments, start=1):
        label = f"Segment {i} ({s.src_in:.2f}s to {s.src_out:.2f}s)"
        if s.src_out <= s.src_in:
            errors.append(f"{label}: end must be after start")
            continue
        if s.src_out > duration + 0.05:
            errors.append(f"{label}: ends after the source ({duration:.2f}s)")
        if s.duration < MIN_SEGMENT_S:
            errors.append(f"{label}: shorter than {MIN_SEGMENT_S}s, which reads as a glitch")
        if not 1.0 <= s.zoom <= MAX_ZOOM:
            errors.append(f"{label}: zoom {s.zoom} is outside 1.0 to {MAX_ZOOM}")

    # Overlaps aren't wrong (a repeated line can be intentional) but are worth flagging.
    ordered = sorted(plan.segments, key=lambda s: s.src_in)
    for a, b in zip(ordered, ordered[1:]):
        if b.src_in < a.src_out - 0.01:
            warnings.append(f"Source {b.src_in:.2f}s to {a.src_out:.2f}s is used twice")

    if info.audio is None:
        warnings.append("Source has no audio; the export will be silent")
    if plan.segments and plan.duration < 1.0:
        errors.append(f"Edit is only {plan.duration:.2f}s long")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)
