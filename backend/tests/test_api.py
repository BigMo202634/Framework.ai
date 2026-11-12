from tests.conftest import make_video, needs_ffmpeg


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_rejects_unsupported_extension(client):
    r = client.post("/api/media", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


@needs_ffmpeg
def test_import_inspect_delete(client, tmp_path):
    video = make_video(tmp_path / "talk.mp4", width=1920, height=1080, seconds=2)
    with video.open("rb") as f:
        r = client.post("/api/media", files={"file": ("talk.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["width"] == 1920 and body["height"] == 1080
    assert body["orientation"] == "horizontal"
    assert body["has_audio"] is True

    media_id = body["media_id"]
    r = client.get(f"/api/media/{media_id}")
    assert r.status_code == 200
    assert r.json()["original_name"] == "talk.mp4"

    assert client.delete(f"/api/media/{media_id}").status_code == 204
    assert client.get(f"/api/media/{media_id}").status_code == 404


@needs_ffmpeg
def test_import_rejects_fake_video(client):
    r = client.post("/api/media", files={"file": ("fake.mp4", b"not really a video", "video/mp4")})
    assert r.status_code == 422
    assert "could not read" in r.json()["detail"]


def test_import_rejects_too_large(client):
    big = b"0" * (6 * 1024 * 1024)  # limit is 5 MB in the test client
    r = client.post("/api/media", files={"file": ("big.mp4", big, "video/mp4")})
    assert r.status_code == 413


def test_bad_media_id_is_404(client):
    assert client.get("/api/media/../../etc").status_code == 404
    assert client.get("/api/media/notanid").status_code == 404


@needs_ffmpeg
def test_auto_edit_end_to_end(client, tmp_path):
    import time

    from tests.conftest import make_talk_video

    video = make_talk_video(tmp_path / "talk.mp4", width=640, height=360)  # small: test upload limit is 5 MB
    with video.open("rb") as f:
        media_id = client.post("/api/media", files={"file": ("talk.mp4", f, "video/mp4")}).json()["media_id"]

    r = client.post(f"/api/media/{media_id}/analyze")
    assert r.status_code == 200
    assert len(r.json()["silences"]) >= 3

    r = client.post(f"/api/media/{media_id}/plan", json={"aspect": "9:16"})
    assert r.status_code == 200
    assert r.json()["validation"]["ok"] is True

    r = client.post(f"/api/media/{media_id}/render", json={"request": {"aspect": "9:16"}})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    for _ in range(120):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.25)
    assert job["status"] == "done", job
    r = client.get(f"/api/media/{media_id}/exports/{job['output']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 10_000


def test_render_rejects_invalid_plan(client, tmp_path):
    import shutil
    if shutil.which("ffprobe") is None:
        return
    from tests.conftest import make_video

    video = make_video(tmp_path / "v.mp4", seconds=2)
    with video.open("rb") as f:
        media_id = client.post("/api/media", files={"file": ("v.mp4", f, "video/mp4")}).json()["media_id"]
    bad = {"media_id": media_id, "segments": [{"src_in": 0, "src_out": 50}]}
    r = client.post(f"/api/media/{media_id}/render", json={"plan": bad})
    assert r.status_code == 422
    assert "ends after the source" in str(r.json())


def test_export_name_is_restricted(client):
    assert client.get("/api/media/0123456789abcdef0123456789abcdef/exports/..%2finfo.json").status_code == 404


@needs_ffmpeg
def test_chat_edits_plan(client, tmp_path):
    from tests.conftest import make_talk_video

    video = make_talk_video(tmp_path / "talk.mp4", width=640, height=360)
    with video.open("rb") as f:
        media_id = client.post("/api/media", files={"file": ("talk.mp4", f, "video/mp4")}).json()["media_id"]
    plan = client.post(f"/api/media/{media_id}/plan", json={"aspect": "9:16"}).json()["plan"]
    before = sum(s["src_out"] - s["src_in"] for s in plan["segments"])

    r = client.post(f"/api/media/{media_id}/chat", json={"message": "cut the first 1 second", "plan": plan, "mode": "rules"})
    assert r.status_code == 200, r.text
    body = r.json()
    after = sum(s["src_out"] - s["src_in"] for s in body["plan"]["segments"])
    assert abs((before - after) - 1.0) < 0.01
    assert body["validation"]["ok"] and body["mode"] == "rules"

    r = client.post(f"/api/media/{media_id}/chat", json={"message": "make it tighter", "plan": body["plan"], "mode": "rules"})
    assert "Re-cut the pacing" in r.json()["reply"]

    r = client.post(f"/api/media/{media_id}/chat", json={"message": "cut 0 to 500", "plan": plan, "mode": "rules"})
    assert "Couldn't do that" in r.json()["reply"]
    assert r.json()["plan"] == plan


def test_creative_cuts_use_the_transcript(client, tmp_path, monkeypatch):
    """With a (fake) transcript, the plan cuts the filler and lists it; the chat can put it back."""
    import app.main as main
    from app.engine.transcribe import Transcript, Word
    from tests.conftest import make_talk_video

    # Tone plays 0-2 s, 3-5 s, 6-8 s. Pretend the middle of the first one is an "um".
    fake = Transcript(model="test", language="en", words=[
        Word(i=0, start=0.1, end=0.6, text="Hello,"),
        Word(i=1, start=0.8, end=1.2, text="um,"),
        Word(i=2, start=1.4, end=1.9, text="everyone."),
        Word(i=3, start=3.1, end=4.9, text="Welcome."),
    ])
    calls = []
    monkeypatch.setattr(main, "transcribe", lambda *a, **k: calls.append(k) or fake)
    client.app.dependency_overrides[main.get_settings]().whisper_model = "test"

    video = make_talk_video(tmp_path / "talk.mp4", width=640, height=360)
    with video.open("rb") as f:
        media_id = client.post("/api/media", files={"file": ("talk.mp4", f, "video/mp4")}).json()["media_id"]

    r = client.post(f"/api/media/{media_id}/plan", json={"aspect": "9:16", "creative_cuts": True})
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert [p["text"] for p in plan["removed"]] == ["um,"]
    assert plan["brain"] == "mock+rules-director"
    # The cut lands between "Hello," and "everyone." and nothing of either word is lost.
    first, second = plan["segments"][0], plan["segments"][1]
    assert 0.6 < first["src_out"] < 0.8 and 1.2 < second["src_in"] < 1.4
    assert len(calls) == 1 and calls[0]["speech"]  # phrase-by-phrase transcription

    r = client.post(f"/api/media/{media_id}/plan", json={"aspect": "9:16", "creative_cuts": False})
    assert r.json()["plan"]["removed"] == []
    assert len(calls) == 1  # transcript is cached

    r = client.post(f"/api/media/{media_id}/chat", json={"message": "keep the ums", "plan": plan, "mode": "rules"})
    body = r.json()
    assert body["changes"] and body["plan"]["removed"] == []


def test_proxy_and_waveform(client, tmp_path):
    from tests.conftest import make_talk_video

    video = make_talk_video(tmp_path / "talk.mp4", width=640, height=360)
    with video.open("rb") as f:
        media_id = client.post("/api/media", files={"file": ("talk.mp4", f, "video/mp4")}).json()["media_id"]

    r = client.get(f"/api/media/{media_id}/waveform")
    assert r.status_code == 200
    w = r.json()
    assert w["rate"] == 50 and 440 <= len(w["peaks"]) <= 460  # 9 s of audio
    # Tone for 2 s, silence for 1 s: loud at 1 s, quiet at 2.5 s.
    assert w["peaks"][50] > 50 and w["peaks"][125] < 5

    r = client.get(f"/api/media/{media_id}/proxy.mp4")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    r = client.get(f"/api/media/{media_id}/proxy.mp4", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100  # seekable in the browser
