"""Audio analysis with FFmpeg: loudness and silence detection.

Silence detection is what lets us remove dead air between sentences. The threshold adapts to
the recording: a quiet room mic and a loud lav need different settings, so by default we
measure the clip's average loudness and set the silence level a fixed amount below it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pydantic import BaseModel


class AudioError(RuntimeError):
    pass


class Interval(BaseModel):
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class AudioAnalysis(BaseModel):
    duration_s: float
    mean_volume_db: float
    max_volume_db: float
    silence_threshold_db: float
    min_silence_s: float
    silences: list[Interval]
    speech: list[Interval]

    @property
    def silence_total_s(self) -> float:
        return round(sum(s.duration for s in self.silences), 3)


def _run(cmd: list[str], timeout: float) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise AudioError(f"'{cmd[0]}' not found. Install FFmpeg and add it to PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError("Audio analysis timed out") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        raise AudioError(f"FFmpeg audio analysis failed: {tail[0]}")
    return result.stderr  # ffmpeg prints filter reports to stderr


def extract_audio(src: Path, dst: Path, ffmpeg: str = "ffmpeg", sample_rate: int = 16000) -> Path:
    """Extract mono 16 kHz WAV, the format speech-to-text models expect."""
    _run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate),
          "-c:a", "pcm_s16le", str(dst)], timeout=600)
    return dst


_MEAN = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf) dB")
_MAX = re.compile(r"max_volume:\s*(-?[\d.]+|-inf) dB")


def measure_volume(src: Path, ffmpeg: str = "ffmpeg") -> tuple[float, float]:
    out = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af", "volumedetect",
                "-f", "null", "-"], timeout=600)
    mean, peak = _MEAN.search(out), _MAX.search(out)
    if not mean or not peak:
        raise AudioError("Could not measure volume (does the file have audio?)")

    def val(m):
        return -91.0 if m.group(1) == "-inf" else float(m.group(1))

    return val(mean), val(peak)


_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def parse_silencedetect(log: str, duration: float) -> list[Interval]:
    """Turn ffmpeg silencedetect output into intervals. A silence still open at EOF ends at duration."""
    silences: list[Interval] = []
    start: float | None = None
    for line in log.splitlines():
        if (m := _SIL_START.search(line)) is not None:
            start = max(0.0, float(m.group(1)))
        elif (m := _SIL_END.search(line)) is not None and start is not None:
            silences.append(Interval(start=round(start, 3), end=round(min(float(m.group(1)), duration), 3)))
            start = None
    if start is not None and start < duration:
        silences.append(Interval(start=round(start, 3), end=round(duration, 3)))
    return silences


def invert(intervals: list[Interval], duration: float) -> list[Interval]:
    """Everything that isn't in `intervals` (sorted, non-overlapping) between 0 and duration."""
    out: list[Interval] = []
    cursor = 0.0
    for iv in sorted(intervals, key=lambda i: i.start):
        if iv.start > cursor:
            out.append(Interval(start=round(cursor, 3), end=round(iv.start, 3)))
        cursor = max(cursor, iv.end)
    if cursor < duration:
        out.append(Interval(start=round(cursor, 3), end=round(duration, 3)))
    return [i for i in out if i.duration > 0.001]


def analyze(
    src: Path,
    duration: float,
    ffmpeg: str = "ffmpeg",
    threshold_db: float | None = None,
    min_silence_s: float = 0.35,
) -> AudioAnalysis:
    mean_db, max_db = measure_volume(src, ffmpeg)
    if threshold_db is None:
        # 18 dB under the average speech level, kept inside a sensible range.
        threshold_db = min(-25.0, max(-55.0, mean_db - 18.0))
    log = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(src), "-vn",
                "-af", f"silencedetect=noise={threshold_db:.1f}dB:d={min_silence_s}",
                "-f", "null", "-"], timeout=600)
    silences = parse_silencedetect(log, duration)
    return AudioAnalysis(
        duration_s=duration,
        mean_volume_db=mean_db,
        max_volume_db=max_db,
        silence_threshold_db=round(threshold_db, 1),
        min_silence_s=min_silence_s,
        silences=silences,
        speech=invert(silences, duration),
    )
