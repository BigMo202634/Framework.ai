"""OpenTimelineIO interchange export for professional NLE handoff.

The project deliberately emits OTIO JSON directly instead of importing the
OpenTimelineIO Python package. The document uses the public OTIO schemas, so
Resolve, Premiere (through an OTIO adapter), and other OTIO-aware tools can
open it while FRAMEWORK AI keeps a small local install.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engine.plan import EditPlan


def _time(seconds: float, rate: float) -> dict[str, Any]:
    return {"OTIO_SCHEMA": "RationalTime.1", "value": seconds * rate, "rate": rate}


def _range(start: float, duration: float, rate: float) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _time(start, rate),
        "duration": _time(duration, rate),
    }


def _reference(source_url: str, source_duration: float, rate: float) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "ExternalReference.1",
        "name": "Source media",
        "target_url": source_url,
        "available_range": _range(0.0, source_duration, rate),
        "available_image_bounds": None,
        "metadata": {},
    }


def _clip(segment: Any, index: int, source_url: str, source_duration: float,
          rate: float) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "Clip.2",
        "name": f"Clip {index:03d}",
        "source_range": _range(segment.src_in, segment.duration, rate),
        "media_references": {
            "DEFAULT_MEDIA": _reference(source_url, source_duration, rate),
        },
        "active_media_reference_key": "DEFAULT_MEDIA",
        "effects": [],
        "markers": [],
        "enabled": True,
        "color": None,
        "metadata": {
            "framework_ai": {
                "segment_index": index - 1,
                "reason": segment.reason,
                "zoom": segment.zoom,
                "focus_x": segment.focus_x,
                "focus_y": segment.focus_y,
            }
        },
    }


def _track(name: str, kind: str, clips: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "Track.1",
        "name": name,
        "kind": kind,
        "children": clips,
        "source_range": None,
        "effects": [],
        "markers": [],
        "enabled": True,
        "metadata": {},
    }


def to_otio(plan: EditPlan, source_path: Path, source_duration: float, rate: float,
            name: str = "FRAMEWORK AI Edit", has_audio: bool = True) -> dict[str, Any]:
    """Translate one validated edit plan into an OTIO JSON document."""
    if rate <= 0:
        raise ValueError("Timeline rate must be greater than zero")
    if source_duration <= 0:
        raise ValueError("Source duration must be greater than zero")

    source_url = Path(source_path).resolve().as_uri()
    video_clips = [
        _clip(segment, index, source_url, source_duration, rate)
        for index, segment in enumerate(plan.segments, start=1)
    ]
    tracks = [_track("V1", "Video", video_clips)]
    if has_audio:
        audio_clips = [
            _clip(segment, index, source_url, source_duration, rate)
            for index, segment in enumerate(plan.segments, start=1)
        ]
        tracks.append(_track("A1", "Audio", audio_clips))

    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": name,
        "global_start_time": None,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": tracks,
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "metadata": {},
        },
        "metadata": {
            "framework_ai": {
                "edit_plan_version": plan.version,
                "media_id": plan.media_id,
                "brain": plan.brain,
                "summary": plan.summary,
                "message": plan.message,
                "duration_s": plan.duration,
                "output": plan.output.model_dump(),
                "captions": plan.captions.model_dump(),
            }
        },
    }
