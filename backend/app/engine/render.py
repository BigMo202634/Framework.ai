"""Renders a validated EditPlan to MP4 with a single FFmpeg command.

Each segment is trimmed, cropped (for reframing and punch-ins), scaled to the output size,
and the pieces are concatenated. Audio gets 10 ms fades at every cut so joins don't click.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from app.engine.plan import EditPlan, Segment, resolve_output
from app.media.probe import MediaInfo

log = logging.getLogger("framework.render")

AUDIO_FADE_S = 0.01


class RenderError(RuntimeError):
    pass


def crop_box(src_w: int, src_h: int, out_w: int, out_h: int, seg: Segment) -> tuple[int, int, int, int]:
    """Largest crop with the output's aspect ratio, shrunk by the zoom, centred on the focus point."""
    target = out_w / out_h
    cw = min(src_w, src_h * target)
    ch = cw / target
    cw, ch = cw / seg.zoom, ch / seg.zoom
    cw, ch = max(2, int(cw) - int(cw) % 2), max(2, int(ch) - int(ch) % 2)
    x = min(max(0.0, seg.focus_x * src_w - cw / 2), src_w - cw)
    y = min(max(0.0, seg.focus_y * src_h - ch / 2), src_h - ch)
    return cw, ch, int(x), int(y)


def build_filter(plan: EditPlan, info: MediaInfo) -> tuple[str, bool]:
    out = resolve_output(plan.output, info)
    has_audio = info.audio is not None
    src_w, src_h = info.display_width, info.display_height
    parts: list[str] = []
    labels: list[str] = []
    for i, seg in enumerate(plan.segments):
        cw, ch, x, y = crop_box(src_w, src_h, out.width, out.height, seg)
        parts.append(
            f"[0:v:0]trim=start={seg.src_in:.3f}:end={seg.src_out:.3f},setpts=PTS-STARTPTS,"
            f"crop={cw}:{ch}:{x}:{y},scale={out.width}:{out.height}:flags=lanczos,setsar=1,"
            f"fps={out.fps},format=yuv420p[v{i}]"
        )
        labels.append(f"[v{i}]")
        if has_audio:
            d = seg.duration
            parts.append(
                f"[0:a:0]atrim=start={seg.src_in:.3f}:end={seg.src_out:.3f},asetpts=PTS-STARTPTS,"
                f"aresample=48000,afade=t=in:d={AUDIO_FADE_S},"
                f"afade=t=out:st={max(0.0, d - AUDIO_FADE_S):.3f}:d={AUDIO_FADE_S}[a{i}]"
            )
            labels.append(f"[a{i}]")
    n = len(plan.segments)
    if has_audio:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=1[outv][outa]")
    else:
        parts.append(f"{''.join(labels)}concat=n={n}:v=1:a=0[outv]")
    return ";\n".join(parts), has_audio


def render(
    plan: EditPlan,
    info: MediaInfo,
    src: Path,
    dst: Path,
    ffmpeg: str = "ffmpeg",
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    out = resolve_output(plan.output, info)
    graph, has_audio = build_filter(plan, info)
    script = dst.with_suffix(".filter.txt")
    script.write_text(graph)

    cmd = [ffmpeg, "-y", "-hide_banner", "-nostats", "-progress", "pipe:1",
           "-i", str(src), "-filter_complex_script", str(script), "-map", "[outv]"]
    if has_audio:
        cmd += ["-map", "[outa]", "-c:a", "aac", "-b:a", f"{out.audio_bitrate_k}k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(out.crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(dst)]

    total_us = max(1.0, plan.duration * 1_000_000)
    log.info("Rendering %d segments (%.1fs) to %s", len(plan.segments), plan.duration, dst.name)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        raise RenderError(f"'{ffmpeg}' not found. Install FFmpeg and add it to PATH.") from exc

    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("out_time_us=") and on_progress:
            try:
                on_progress(min(0.99, int(line.split("=", 1)[1]) / total_us))
            except ValueError:
                pass
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        tail = [ln for ln in stderr.strip().splitlines() if ln.strip()][-3:]
        raise RenderError("FFmpeg render failed: " + (" | ".join(tail) or "unknown error"))
    script.unlink(missing_ok=True)
    if on_progress:
        on_progress(1.0)
    return dst
