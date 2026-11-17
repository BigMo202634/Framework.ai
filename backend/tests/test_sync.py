"""Lip-sync guard: a test clip flashes white and beeps at the same instant every 2 seconds.
After an edit with many cuts, every flash must still line up with its beep.

This test exists because an earlier renderer let audio drift ~30 ms ahead per cut
(167 ms after six cuts), which is clearly visible on a talking head."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.engine.plan import EditPlan, OutputSettings, Segment
from app.engine.render import render
from app.media.probe import probe
from tests.conftest import needs_ffmpeg

SR = 48000
CUTS = [(0.37, 3.71), (4.23, 7.91), (8.55, 12.13), (13.02, 17.44), (18.31, 21.87), (22.5, 26.9)]


def make_flash_beep(path: Path, rate: str) -> Path:
    fps = f"({rate})"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=black:s=640x360:r={rate}:d=28,geq=lum='if(eq(mod(N,60),0),235,16)':cb=128:cr=128",
        "-f", "lavfi", "-i", f"aevalsrc='if(lt(mod(t*{fps},60),1),0.8*sin(2*PI*1000*t),0)':s=44100:d=28",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return path


def flash_beep_offsets(path: Path) -> list[float]:
    pts = [float(x.strip(",")) for x in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.split() if x.strip(",")]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", "scale=8:8,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    luma = np.frombuffer(raw, np.uint8).reshape(-1, 64).mean(1)
    flashes = [pts[i] for i in range(1, min(len(luma), len(pts))) if luma[i] > 120 >= luma[i - 1]]
    audio = np.abs(np.frombuffer(subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True).stdout, np.float32))
    loud = audio > 0.3
    beeps = [i / SR for i in range(1, len(loud)) if loud[i] and not loud[max(0, i - 480):i].any()]
    return [min(beeps, key=lambda b: abs(b - f)) - f for f in flashes]


@needs_ffmpeg
@pytest.mark.parametrize("rate", ["30", "30000/1001"])
@pytest.mark.parametrize("aspect", ["9:16", "16:9"])
def test_lip_sync_holds_across_many_cuts(tmp_path, rate, aspect):
    src = make_flash_beep(tmp_path / "src.mp4", rate)
    info = probe(src)
    plan = EditPlan(media_id="m", output=OutputSettings(aspect=aspect), segments=[
        Segment(src_in=a, src_out=b, zoom=1.15 if i % 2 else 1.0) for i, (a, b) in enumerate(CUTS)])
    out = render(plan, info, src, tmp_path / "out.mp4")
    offsets = flash_beep_offsets(out)
    assert len(offsets) >= 8
    worst = max(abs(o) for o in offsets)
    assert worst < 0.015, f"audio/video out of sync by up to {worst * 1000:.0f} ms: {[round(o * 1000) for o in offsets]}"
