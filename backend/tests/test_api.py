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
