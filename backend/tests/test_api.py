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
