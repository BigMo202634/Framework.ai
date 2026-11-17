import json
from pathlib import Path

import pytest

from app.engine.interchange import to_otio
from app.engine.plan import EditPlan, Segment
from tests.conftest import needs_ffmpeg


def test_otio_preserves_cuts_and_editor_metadata(tmp_path):
    source = tmp_path / "source clip.mp4"
    source.touch()
    plan = EditPlan(
        media_id="a" * 32,
        brain="test-director",
        summary="Tight talking-head cut",
        segments=[
            Segment(src_in=1.0, src_out=2.5, reason="Keep the hook"),
            Segment(src_in=5.0, src_out=8.0, zoom=1.2, focus_x=0.4, focus_y=0.3,
                    reason="Remove a false start"),
        ],
    )

    timeline = to_otio(plan, source, source_duration=10.0, rate=25.0)

    assert timeline["OTIO_SCHEMA"] == "Timeline.1"
    video, audio = timeline["tracks"]["children"]
    assert video["kind"] == "Video" and audio["kind"] == "Audio"
    assert len(video["children"]) == len(audio["children"]) == 2
    first, second = video["children"]
    assert first["source_range"]["start_time"]["value"] == 25.0
    assert first["source_range"]["duration"]["value"] == 37.5
    assert second["metadata"]["framework_ai"] == {
        "segment_index": 1,
        "reason": "Remove a false start",
        "zoom": 1.2,
        "focus_x": 0.4,
        "focus_y": 0.3,
    }
    assert first["active_media_reference_key"] == "DEFAULT_MEDIA"
    assert first["media_references"]["DEFAULT_MEDIA"]["target_url"] == source.resolve().as_uri()
    assert timeline["metadata"]["framework_ai"]["duration_s"] == 4.5


def test_otio_can_omit_audio(tmp_path):
    plan = EditPlan(media_id="b" * 32, segments=[Segment(src_in=0, src_out=1)])
    timeline = to_otio(plan, tmp_path / "silent.mp4", 2.0, 30.0, has_audio=False)
    assert [track["kind"] for track in timeline["tracks"]["children"]] == ["Video"]


@pytest.mark.parametrize("duration,rate", [(0, 30), (10, 0), (-1, 30), (10, -1)])
def test_otio_rejects_invalid_timebase(tmp_path, duration, rate):
    plan = EditPlan(media_id="c" * 32, segments=[Segment(src_in=0, src_out=1)])
    with pytest.raises(ValueError):
        to_otio(plan, Path(tmp_path / "source.mp4"), duration, rate)


@needs_ffmpeg
def test_otio_endpoint_returns_downloadable_timeline(client, tmp_path):
    from tests.conftest import make_video

    video = make_video(tmp_path / "talk.mp4", width=640, height=360, seconds=2)
    with video.open("rb") as handle:
        media_id = client.post(
            "/api/media", files={"file": ("talk.mp4", handle, "video/mp4")}
        ).json()["media_id"]
    plan = client.post(f"/api/media/{media_id}/plan", json={"aspect": "16:9"}).json()["plan"]

    response = client.post(f"/api/media/{media_id}/timeline.otio", json={"plan": plan})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.otio+json")
    assert response.headers["content-disposition"].endswith('.otio"')
    timeline = json.loads(response.content)
    assert timeline["OTIO_SCHEMA"] == "Timeline.1"
    assert timeline["metadata"]["framework_ai"]["media_id"] == media_id
    assert timeline["tracks"]["children"][0]["children"]
