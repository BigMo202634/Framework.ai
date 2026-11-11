"""Timeline commands: the one set of edit operations shared by the chat, the API and (later) MCP.

All times are in OUTPUT timeline seconds, i.e. what the user sees on the preview player, not the
original recording. Commands never touch pixels; they rewrite the EditPlan, which is then
validated and rendered like any other plan.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.engine.plan import Aspect, EditPlan, Segment
from app.engine.validate import MIN_SEGMENT_S

Op = Literal["set_aspect", "cut", "zoom", "punch_ins", "replan"]


class Command(BaseModel):
    op: Op
    aspect: Aspect | None = None
    start: float | None = None      # output seconds
    end: float | None = None        # output seconds
    zoom: float | None = None
    enabled: bool | None = None
    # replan settings
    padding_s: float | None = None
    keep_pauses_under_s: float | None = None
    remove_silences: bool | None = None
    creative_cuts: bool | None = None  # cut fillers, stutters, retakes and repeats from the transcript


class CommandError(ValueError):
    pass


def output_starts(plan: EditPlan) -> list[float]:
    starts, t = [], 0.0
    for s in plan.segments:
        starts.append(t)
        t += s.duration
    return starts


def split_at(plan: EditPlan, t: float) -> int:
    """Make sure a segment boundary exists at output time t. Returns the index of the segment
    that starts at t (len(segments) if t is the end). Snaps to an existing boundary when the
    split would leave a piece shorter than the minimum segment length."""
    t = max(0.0, min(t, plan.duration))
    starts = output_starts(plan)
    for i, (seg, s0) in enumerate(zip(plan.segments, starts)):
        s1 = s0 + seg.duration
        if t <= s0 + 1e-6:
            return i
        if t < s1 - 1e-6:
            offset = t - s0
            if offset < MIN_SEGMENT_S:
                return i
            if seg.duration - offset < MIN_SEGMENT_S:
                return i + 1
            cut_src = round(seg.src_in + offset, 3)
            left = seg.model_copy(update={"src_out": cut_src})
            right = seg.model_copy(update={"src_in": cut_src})
            plan.segments[i:i + 1] = [left, right]
            return i + 1
    return len(plan.segments)


def _range(plan: EditPlan, cmd: Command) -> tuple[float, float]:
    start = 0.0 if cmd.start is None else cmd.start
    end = plan.duration if cmd.end is None else cmd.end
    if end <= start:
        raise CommandError(f"End ({end:.2f}s) must be after start ({start:.2f}s)")
    if start >= plan.duration:
        raise CommandError(f"{start:.2f}s is past the end of the edit ({plan.duration:.2f}s)")
    return start, min(end, plan.duration)


def apply(plan: EditPlan, cmd: Command, replan=None) -> tuple[EditPlan, str]:
    """Apply one command and return (new plan, plain-English description of what changed).

    `replan` is a callback(cmd, punch_ins) -> EditPlan,
    used for pacing changes that need the original audio analysis.
    """
    plan = plan.model_copy(deep=True)

    if cmd.op == "set_aspect":
        if cmd.aspect is None:
            raise CommandError("Which format? 9:16, 16:9, 1:1, 4:5 or source")
        plan.output.aspect = cmd.aspect
        plan.output.width = plan.output.height = None
        return plan, f"Changed the format to {cmd.aspect}"

    if cmd.op == "cut":
        start, end = _range(plan, cmd)
        before = plan.duration
        i = split_at(plan, start)
        j = split_at(plan, end)
        if j <= i:
            raise CommandError("That range is too short to cut")
        del plan.segments[i:j]
        if not plan.segments:
            raise CommandError("That would cut the whole video")
        return plan, f"Cut {start:.1f}s to {end:.1f}s ({before - plan.duration:.1f}s removed)"

    if cmd.op == "zoom":
        start, end = _range(plan, cmd)
        z = cmd.zoom if cmd.zoom is not None else 1.2
        if not 1.0 <= z <= 2.0:
            raise CommandError("Zoom has to be between 1.0 (none) and 2.0")
        i = split_at(plan, start)
        j = split_at(plan, end)
        for seg in plan.segments[i:j]:
            seg.zoom = z
            seg.reason = "zoom from chat"
        what = "Removed the zoom" if z == 1.0 else f"Zoomed in {int(round((z - 1) * 100))}%"
        return plan, f"{what} from {start:.1f}s to {end:.1f}s"

    if cmd.op == "punch_ins":
        enabled = True if cmd.enabled is None else cmd.enabled
        for i, seg in enumerate(plan.segments):
            seg.zoom = 1.15 if enabled and i % 2 == 1 else 1.0
        return plan, "Added punch-ins on every other cut" if enabled else "Removed all punch-ins"

    if cmd.op == "replan":
        if replan is None:
            raise CommandError("Pacing changes need the audio analysis")
        punch = any(s.zoom > 1.0 for s in plan.segments)
        new = replan(cmd, punch)
        new.output = plan.output
        what = "Re-cut the pacing"
        if cmd.creative_cuts is not None:
            what = ("Cut the fillers, stutters and retakes" if cmd.creative_cuts
                    else "Put the fillers and repeats back")
        return new, (f"{what}: {len(new.segments)} parts, {new.duration:.1f}s long "
                     "(earlier manual cuts were reset)")

    raise CommandError(f"Unknown command {cmd.op}")


def make_segments(ranges: list[tuple[float, float]]) -> list[Segment]:
    return [Segment(src_in=a, src_out=b) for a, b in ranges]
