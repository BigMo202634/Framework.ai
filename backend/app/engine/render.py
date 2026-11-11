"""Renders a validated EditPlan to MP4.

How it works (and why):
1. Each segment is rendered on its own: FFmpeg seeks straight to the segment, crops/zooms,
   scales to the output size and writes an intermediate file (H.264 video + uncompressed audio).
2. The intermediates are joined with FFmpeg's concat demuxer (video copied, audio encoded once).

An earlier version used one big filter graph with a trim per segment. On a real 4.5-minute
phone clip with 48 cuts that ran out of memory, because every branch buffered decoded frames
while waiting its turn. Rendering per segment keeps memory flat whatever the length, and lets
us later re-render only the segments a chat edit changed.

Audio gets 10 ms fades at every cut so joins don't click.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.engine.plan import EditPlan, OutputSettings, Segment, resolve_output
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


def segment_command(seg: Segment, info: MediaInfo, out: OutputSettings, src: Path, dst: Path,
                    ffmpeg: str = "ffmpeg") -> list[str]:
    cw, ch, x, y = crop_box(info.display_width, info.display_height, out.width, out.height, seg)
    vf = (f"crop={cw}:{ch}:{x}:{y},scale={out.width}:{out.height}:flags=lanczos,setsar=1,"
          f"fps={out.fps},format=yuv420p")
    # Snap to whole frames so video and audio lengths match exactly; otherwise tiny
    # rounding differences add up over dozens of cuts and lips drift out of sync.
    frames = max(1, round(seg.duration * out.fps))
    d = frames / out.fps
    cmd = [ffmpeg, "-y", "-v", "error", "-ss", f"{seg.src_in:.3f}", "-t", f"{d + 0.1:.3f}",
           "-i", str(src), "-map", "0:v:0", "-vf", vf, "-frames:v", str(frames),
           "-c:v", "libx264", "-preset", "medium", "-crf", str(out.crf)]
    if info.audio is not None:
        af = (f"aresample=48000,afade=t=in:d={AUDIO_FADE_S},"
              f"afade=t=out:st={max(0.0, d - AUDIO_FADE_S):.3f}:d={AUDIO_FADE_S}")
        cmd += ["-map", "0:a:0", "-af", af, "-c:a", "pcm_s16le", "-ac", "2"]
    cmd += ["-t", f"{d:.6f}", str(dst)]
    return cmd


def segment_key(seg: Segment, info: MediaInfo, out: OutputSettings) -> str:
    """Stable id for a rendered segment, so unchanged segments can be reused between edits."""
    raw = f"{info.path}|{seg.src_in:.3f}|{seg.src_out:.3f}|{seg.zoom}|{seg.focus_x}|{seg.focus_y}|" \
          f"{out.width}x{out.height}@{out.fps}|crf{out.crf}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _run(cmd: list[str]) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RenderError(f"'{cmd[0]}' not found. Install FFmpeg and add it to PATH.") from exc
    if result.returncode != 0:
        tail = [ln for ln in (result.stderr or "").strip().splitlines() if ln.strip()][-3:]
        raise RenderError("FFmpeg render failed: " + (" | ".join(tail) or "unknown error"))


def render(
    plan: EditPlan,
    info: MediaInfo,
    src: Path,
    dst: Path,
    ffmpeg: str = "ffmpeg",
    on_progress: Callable[[float], None] | None = None,
    cache_dir: Path | None = None,
) -> Path:
    """Render the plan. If cache_dir is given, segments already rendered with the same settings are reused."""
    out = resolve_output(plan.output, info)
    total = max(0.001, plan.duration)
    done = 0.0
    tmp = Path(tempfile.mkdtemp(prefix="fw_render_", dir=dst.parent))
    cache = cache_dir or tmp
    cache.mkdir(parents=True, exist_ok=True)
    log.info("Rendering %d segments (%.1fs) to %s", len(plan.segments), plan.duration, dst.name)
    try:
        parts: list[Path] = []
        for seg in plan.segments:
            part = cache / f"seg_{segment_key(seg, info, out)}.mkv"
            if not part.is_file():
                partial = part.with_suffix(".partial.mkv")
                _run(segment_command(seg, info, out, src, partial, ffmpeg))
                partial.replace(part)
            parts.append(part)
            done += seg.duration
            if on_progress:
                on_progress(min(0.95, 0.95 * done / total))

        listing = tmp / "concat.txt"
        listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts))
        cmd = [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
               "-map", "0:v:0", "-c:v", "copy"]
        if info.audio is not None:
            cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", f"{out.audio_bitrate_k}k"]
        cmd += ["-movflags", "+faststart", str(dst)]
        _run(cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if on_progress:
        on_progress(1.0)
    return dst
