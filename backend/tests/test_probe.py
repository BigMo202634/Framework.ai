import pytest

from app.media.probe import ProbeError, parse_ffprobe_json, probe
from tests.conftest import make_video, needs_ffmpeg


def test_parse_handles_rotation_and_fps():
    data = {
        "format": {"format_name": "mov,mp4", "duration": "12.5", "size": "1000", "bit_rate": "640"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160,
             "avg_frame_rate": "30000/1001", "pix_fmt": "yuv420p10le", "bits_per_raw_sample": "10",
             "side_data_list": [{"rotation": -90}]},
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
        ],
    }
    info = parse_ffprobe_json(data, "x.mov")
    assert info.video.fps == 29.97
    assert info.video.bit_depth == 10
    assert info.orientation == "vertical"  # phone shot rotated 90 degrees
    assert (info.display_width, info.display_height) == (2160, 3840)
    assert info.audio.sample_rate == 48000


def test_parse_skips_cover_art():
    data = {
        "format": {"format_name": "mp4", "duration": "1"},
        "streams": [{"index": 0, "codec_type": "video", "codec_name": "mjpeg", "width": 300, "height": 300,
                     "disposition": {"attached_pic": 1}}],
    }
    assert parse_ffprobe_json(data, "a.mp4").video is None


@needs_ffmpeg
def test_probe_real_file(tmp_path):
    path = make_video(tmp_path / "talk.mp4", width=1080, height=1920, seconds=2, fps=30)
    info = probe(path)
    assert info.video.codec == "h264"
    assert info.video.width == 1080 and info.video.height == 1920
    assert info.video.fps == 30
    assert info.audio is not None
    assert 1.9 <= info.duration_s <= 2.2
    assert info.orientation == "vertical"


@needs_ffmpeg
def test_probe_rejects_non_video(tmp_path):
    bad = tmp_path / "notes.mp4"
    bad.write_text("this is not a video")
    with pytest.raises(ProbeError):
        probe(bad)


def test_probe_missing_file(tmp_path):
    with pytest.raises(ProbeError, match="not found"):
        probe(tmp_path / "nope.mp4")
