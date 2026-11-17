"""FFprobe inspection: turns a media file into a validated MediaInfo object.

This is the first deterministic building block of the pipeline. Everything later
(silence detection, the edit plan, rendering) relies on these numbers being right.
"""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from pydantic import BaseModel


class ProbeError(RuntimeError):
    """Raised when ffprobe cannot read a file or the file has no usable video."""


class VideoStream(BaseModel):
    index: int
    codec: str
    width: int
    height: int
    fps: float
    pix_fmt: str | None = None
    rotation: int = 0
    # Colour metadata. Log footage (S-Log3, C-Log, V-Log...) is usually NOT tagged here,
    # so these are hints only; the user's log-profile choice wins later on.
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    bit_depth: int | None = None


class AudioStream(BaseModel):
    index: int
    codec: str
    sample_rate: int
    channels: int


class MediaInfo(BaseModel):
    path: str
    container: str
    duration_s: float
    size_bytes: int
    bitrate: int | None = None
    video: VideoStream | None = None
    audio: AudioStream | None = None

    @property
    def display_width(self) -> int:
        if not self.video:
            return 0
        return self.video.height if abs(self.video.rotation) in (90, 270) else self.video.width

    @property
    def display_height(self) -> int:
        if not self.video:
            return 0
        return self.video.width if abs(self.video.rotation) in (90, 270) else self.video.height

    @property
    def orientation(self) -> str:
        w, h = self.display_width, self.display_height
        if not w or not h:
            return "unknown"
        if h > w:
            return "vertical"
        return "square" if w == h else "horizontal"


def _parse_fps(rate: str | None) -> float:
    if not rate or rate in ("0/0", "0"):
        return 0.0
    try:
        return round(float(Fraction(rate)), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _rotation(stream: dict) -> int:
    # Newer ffmpeg reports rotation in side_data_list (display matrix); older in tags.rotate.
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            try:
                return int(side["rotation"])
            except (TypeError, ValueError):
                pass
    try:
        return int(stream.get("tags", {}).get("rotate", 0))
    except (TypeError, ValueError):
        return 0


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_ffprobe_json(data: dict, path: str) -> MediaInfo:
    """Build MediaInfo from ffprobe's JSON. Split out so it can be tested without ffprobe."""
    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    video = None
    audio = None
    for s in streams:
        kind = s.get("codec_type")
        # Skip cover art / thumbnails that ffprobe reports as video streams.
        if kind == "video" and video is None and not (s.get("disposition") or {}).get("attached_pic"):
            video = VideoStream(
                index=s["index"],
                codec=s.get("codec_name", "unknown"),
                width=int(s.get("width") or 0),
                height=int(s.get("height") or 0),
                fps=_parse_fps(s.get("avg_frame_rate")) or _parse_fps(s.get("r_frame_rate")),
                pix_fmt=s.get("pix_fmt"),
                rotation=_rotation(s),
                color_space=s.get("color_space"),
                color_transfer=s.get("color_transfer"),
                color_primaries=s.get("color_primaries"),
                bit_depth=_int_or_none(s.get("bits_per_raw_sample")),
            )
        elif kind == "audio" and audio is None:
            audio = AudioStream(
                index=s["index"],
                codec=s.get("codec_name", "unknown"),
                sample_rate=int(s.get("sample_rate") or 0),
                channels=int(s.get("channels") or 0),
            )

    duration = fmt.get("duration")
    if duration is None and video is not None:
        duration = next((s.get("duration") for s in streams if s.get("index") == video.index), None)

    return MediaInfo(
        path=path,
        container=fmt.get("format_name", "unknown"),
        duration_s=round(float(duration or 0.0), 3),
        size_bytes=int(fmt.get("size") or 0),
        bitrate=_int_or_none(fmt.get("bit_rate")),
        video=video,
        audio=audio,
    )


def probe(path: str | Path, ffprobe_path: str = "ffprobe", timeout_s: float = 30.0) -> MediaInfo:
    """Run ffprobe on a file and return MediaInfo. Raises ProbeError with a readable message."""
    path = Path(path)
    if not path.is_file():
        raise ProbeError(f"File not found: {path}")

    cmd = [
        ffprobe_path,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except FileNotFoundError as exc:
        raise ProbeError(
            f"ffprobe not found at '{ffprobe_path}'. Install FFmpeg and make sure ffprobe is on your PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out after {timeout_s}s on {path.name}") from exc

    if result.returncode != 0:
        msg = (result.stderr or "").strip().splitlines()
        raise ProbeError(f"ffprobe could not read {path.name}: {msg[-1] if msg else 'unknown error'}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON for {path.name}") from exc

    info = parse_ffprobe_json(data, str(path))
    if info.video is None:
        raise ProbeError(f"{path.name} has no video stream")
    return info
