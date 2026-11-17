import pytest

from app.brain.base import EditRequest
from app.brain.mock import MockEditorBrain, keep_ranges
from app.engine.audio import Interval, analyze, invert, parse_silencedetect
from app.engine.plan import EditPlan, OutputSettings, Segment, resolve_output
from app.engine.render import crop_box, render
from app.engine.validate import validate_plan
from app.media.probe import AudioStream, MediaInfo, VideoStream, probe
from tests.conftest import make_talk_video, needs_ffmpeg


def fake_info(duration=10.0, w=1920, h=1080, audio=True) -> MediaInfo:
    return MediaInfo(
        path="x.mp4", container="mp4", duration_s=duration, size_bytes=1,
        video=VideoStream(index=0, codec="h264", width=w, height=h, fps=30.0),
        audio=AudioStream(index=1, codec="aac", sample_rate=48000, channels=2) if audio else None,
    )


def test_parse_silencedetect_handles_open_silence():
    log = "[silencedetect] silence_start: 1.5\n[silencedetect] silence_end: 2.2 | silence_duration: 0.7\n" \
          "[silencedetect] silence_start: 9.1\n"
    s = parse_silencedetect(log, 10.0)
    assert [(i.start, i.end) for i in s] == [(1.5, 2.2), (9.1, 10.0)]


def test_invert():
    speech = invert([Interval(start=1, end=2), Interval(start=5, end=6)], 8)
    assert [(i.start, i.end) for i in speech] == [(0, 1), (2, 5), (6, 8)]


def test_keep_ranges_pads_and_merges():
    speech = [Interval(start=1.0, end=2.0), Interval(start=2.3, end=3.0), Interval(start=6.0, end=7.0)]
    kept = keep_ranges(speech, 10.0, padding=0.1, merge_gap=0.25)
    # 1.9-2.4 gap after padding is 0.1 -> merged; 3.1 to 5.9 is a real pause -> cut
    assert [(k.start, k.end) for k in kept] == [(0.9, 3.1), (5.9, 7.1)]


def test_validator_catches_bad_plans():
    info = fake_info(duration=10)
    plan = EditPlan(media_id="m", segments=[
        Segment(src_in=2, src_out=1),
        Segment(src_in=9, src_out=12),
        Segment(src_in=3, src_out=3.1),
        Segment(src_in=4, src_out=6, zoom=3.0),
    ])
    result = validate_plan(plan, info, "m")
    assert not result.ok
    text = " ".join(result.errors)
    assert "end must be after start" in text
    assert "ends after the source" in text
    assert "shorter than" in text
    assert "zoom 3.0" in text


def test_validator_accepts_good_plan_and_warns_on_reuse():
    plan = EditPlan(media_id="m", segments=[Segment(src_in=0, src_out=3), Segment(src_in=2, src_out=5)])
    result = validate_plan(plan, fake_info(), "m")
    assert result.ok
    assert result.warnings


def test_crop_box_vertical_from_horizontal():
    # 16:9 source to 9:16 output: full height, narrow centred column
    cw, ch, x, y = crop_box(1920, 1080, 1080, 1920, Segment(src_in=0, src_out=1, focus_x=0.5))
    assert (cw, ch) == (606, 1080)
    assert abs((x + cw / 2) - 960) <= 2
    # punch-in shrinks the crop
    cw2, ch2, _, _ = crop_box(1920, 1080, 1920, 1080, Segment(src_in=0, src_out=1, zoom=1.2))
    assert cw2 == 1600 and ch2 == 900


def test_resolve_output_caps_source_at_1080p():
    out = resolve_output(OutputSettings(aspect="source"), fake_info(w=3840, h=2160))
    assert (out.width, out.height) == (1920, 1080)
    assert resolve_output(OutputSettings(aspect="9:16"), fake_info()).height == 1920


def test_mock_brain_alternates_punch_ins():
    info = fake_info(duration=9)
    from app.engine.audio import AudioAnalysis
    audio = AudioAnalysis(duration_s=9, mean_volume_db=-20, max_volume_db=-3, silence_threshold_db=-38,
                          min_silence_s=0.35, silences=[], speech=[
                              Interval(start=0, end=2), Interval(start=3, end=5), Interval(start=6, end=8)])
    plan = MockEditorBrain().plan("m", info, audio, EditRequest(aspect="9:16"))
    assert [s.zoom for s in plan.segments] == [1.0, 1.15, 1.0]
    assert validate_plan(plan, info, "m").ok


@needs_ffmpeg
def test_analyze_finds_silences(tmp_path):
    video = make_talk_video(tmp_path / "talk.mp4")
    info = probe(video)
    result = analyze(video, info.duration_s)
    starts = [round(s.start) for s in result.silences]
    assert starts[:3] == [2, 5, 8]
    assert 2.5 <= result.silence_total_s <= 3.5


@needs_ffmpeg
@pytest.mark.parametrize("aspect,size", [("9:16", (1080, 1920)), ("source", (1920, 1080))])
def test_full_pipeline_renders_playable_mp4(tmp_path, aspect, size):
    video = make_talk_video(tmp_path / "talk.mp4")
    info = probe(video)
    audio = analyze(video, info.duration_s)
    plan = MockEditorBrain().plan("m", info, audio, EditRequest(aspect=aspect))
    assert validate_plan(plan, info, "m").ok
    progress = []
    out = render(plan, info, video, tmp_path / "edit.mp4", on_progress=progress.append)
    result = probe(out)
    assert (result.video.width, result.video.height) == size
    assert result.audio is not None
    # ~6 s of tone plus padding; 3 s of silence removed
    assert 6.0 <= result.duration_s <= 7.2
    assert abs(result.duration_s - plan.duration) < 0.25
    assert progress[-1] == 1.0
