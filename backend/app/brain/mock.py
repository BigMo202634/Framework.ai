"""Mock Editor Brain: rule-based, free, deterministic.

It does what a junior editor's first pass does: cut dead air, keep a little breathing room
around each line, and alternate between the wide shot and a punch-in on every cut so jump
cuts feel intentional. The Claude brain will replace this decision-making later; the output
format stays the same.
"""

from __future__ import annotations

from app.brain.base import EditRequest
from app.engine.audio import AudioAnalysis, Interval
from app.engine.plan import EditPlan, OutputSettings, Segment
from app.engine.validate import MIN_SEGMENT_S
from app.media.probe import MediaInfo


def keep_ranges(speech: list[Interval], duration: float, padding: float, merge_gap: float) -> list[Interval]:
    """Pad each spoken part, then merge parts whose gap is short enough to keep."""
    padded = [Interval(start=max(0.0, s.start - padding), end=min(duration, s.end + padding)) for s in speech]
    merged: list[Interval] = []
    for iv in sorted(padded, key=lambda i: i.start):
        if merged and iv.start - merged[-1].end <= merge_gap:
            merged[-1] = Interval(start=merged[-1].start, end=max(merged[-1].end, iv.end))
        else:
            merged.append(iv)
    return [Interval(start=round(i.start, 3), end=round(i.end, 3)) for i in merged if i.duration >= MIN_SEGMENT_S]


class MockEditorBrain:
    name = "mock"

    def plan(self, media_id: str, info: MediaInfo, audio: AudioAnalysis | None,
             request: EditRequest) -> EditPlan:
        duration = info.duration_s
        if request.remove_silences and audio is not None and audio.speech:
            ranges = keep_ranges(audio.speech, duration, request.padding_s, request.keep_pauses_under_s)
        else:
            ranges = [Interval(start=0.0, end=duration)]
        if not ranges:  # everything was silence; keep the whole clip rather than nothing
            ranges = [Interval(start=0.0, end=duration)]

        segments = []
        for i, r in enumerate(ranges):
            punch = request.punch_ins and len(ranges) > 1 and i % 2 == 1
            segments.append(Segment(
                src_in=r.start,
                src_out=r.end,
                zoom=request.punch_in_zoom if punch else 1.0,
                reason="punch-in to hide the jump cut" if punch else "wide",
            ))

        kept = sum(s.duration for s in segments)
        removed = max(0.0, duration - kept)
        return EditPlan(
            media_id=media_id,
            brain=self.name,
            summary=f"Kept {len(segments)} spoken parts ({kept:.1f}s), removed {removed:.1f}s of silence.",
            segments=segments,
            output=OutputSettings(aspect=request.aspect),
        )
