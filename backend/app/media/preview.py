"""Lightweight files for the editor: a proxy video for smooth scrubbing, and an audio waveform.

Why a proxy: phone footage is often 1080p/4K HEVC, which many browsers can't play or scrub
smoothly. Like DaVinci's proxy media, we make a small H.264 copy (640 px on the long side,
a keyframe every half second) used only for previewing. Renders always use the original.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import numpy as np

from app.media.probe import MediaInfo

PROXY_NAME = "proxy.mp4"
WAVEFORM_RATE = 50  # peaks per second of source


class PreviewError(RuntimeError):
    pass


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def make_proxy(src: Path, folder: Path, info: MediaInfo, ffmpeg: str = "ffmpeg") -> Path:
    """Create (once) and return the proxy video. Safe to call from several requests at once."""
    dst = folder / PROXY_NAME
    with _lock(str(dst)):
        if dst.is_file():
            return dst
        fps = info.video.fps if info.video and info.video.fps > 0 else 30
        long_side = "640:-2" if info.display_width >= info.display_height else "-2:640"
        tmp = dst.with_suffix(".partial.mp4")
        cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-map", "0:v:0",
               "-vf", f"scale={long_side},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "28", "-g", str(max(1, round(fps / 2)))]
        if info.audio is not None:
            cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k", "-ac", "2"]
        cmd += ["-movflags", "+faststart", str(tmp)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise PreviewError(f"'{ffmpeg}' not found. Install FFmpeg and add it to PATH.") from exc
        if result.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise PreviewError("Could not make the preview video: " + result.stderr.strip()[-300:])
        tmp.replace(dst)
        return dst


def waveform(src: Path, ffmpeg: str = "ffmpeg", rate: int = WAVEFORM_RATE) -> list[int]:
    """Peak level (0-100) for each 1/rate second of the first audio track."""
    sr = 8000
    cmd = [ffmpeg, "-v", "error", "-i", str(src), "-map", "0:a:0", "-ac", "1", "-ar", str(sr),
           "-f", "s16le", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise PreviewError(f"'{ffmpeg}' not found. Install FFmpeg and add it to PATH.") from exc
    if result.returncode != 0:
        raise PreviewError("Could not read the audio: " + result.stderr.decode(errors="replace").strip()[-300:])
    samples = np.abs(np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32))
    if samples.size == 0:
        return []
    step = sr // rate
    n = samples.size // step
    peaks = samples[: n * step].reshape(n, step).max(axis=1)
    top = float(np.percentile(peaks, 99.5)) or 1.0
    return [int(min(100, round(p / top * 100))) for p in peaks]
