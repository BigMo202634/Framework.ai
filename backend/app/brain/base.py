"""Editor Brain interface. Every brain (mock, Claude, a local model) takes the same inputs and
returns an EditPlan, so the rest of the pipeline never knows which one is running."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.engine.audio import AudioAnalysis
from app.engine.plan import Aspect, EditPlan
from app.media.probe import MediaInfo


class EditRequest(BaseModel):
    aspect: Aspect = "9:16"
    remove_silences: bool = True
    # Creative director: cut fillers (um, uh, em), stutters, retakes and repeated lines from the transcript.
    creative_cuts: bool = True
    punch_ins: bool = True
    # Silence kept around each spoken part so words aren't clipped.
    padding_s: float = 0.12
    # Pauses shorter than this stay in; they sound natural.
    keep_pauses_under_s: float = 0.25
    punch_in_zoom: float = 1.15


class EditorBrain(Protocol):
    name: str

    def plan(self, media_id: str, info: MediaInfo, audio: AudioAnalysis | None,
             request: EditRequest, creative=None) -> EditPlan: ...
