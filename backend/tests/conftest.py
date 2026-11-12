import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/FFprobe not installed",
)


def make_video(path: Path, width=1080, height=1920, seconds=3, fps=30, audio=True) -> Path:
    """Generate a small test clip with FFmpeg (colour bars + a 440 Hz tone)."""
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def make_talk_video(path: Path, seconds=9, width=1920, height=1080) -> Path:
    """A clip whose 'speech' is a tone that plays 2 s, then 1 s of silence, repeating.

    Expected silences: 2-3 s, 5-6 s, 8-9 s.
    """
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"aevalsrc='0.5*sin(2*PI*440*t)*lt(mod(t,3),2)':s=48000:d={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True)
    return path


@pytest.fixture
def client(tmp_path):
    settings = Settings(storage_dir=tmp_path / "storage", max_upload_mb=5, whisper_model="", make_proxies=False)
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()
