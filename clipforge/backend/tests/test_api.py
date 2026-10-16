"""API tests, including a full demo-mode run (sample video -> analysis -> real MP4s -> ZIP)."""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app

from .conftest import needs_ffmpeg

client = TestClient(app)


def test_health_and_config_do_not_leak_keys(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-ant-secret-value")
    r = client.get("/api/config")
    assert r.status_code == 200
    assert "sk-ant-secret-value" not in r.text
    assert r.json()["has_anthropic_key"] is True
    assert client.get("/api/health").json()["ok"] is True


def test_validate_endpoint():
    assert client.get("/api/validate", params={"url": "https://youtu.be/dQw4w9WgXcQ"}).json()["valid"] is True
    bad = client.get("/api/validate", params={"url": "https://vimeo.com/1"}).json()
    assert bad["valid"] is False and bad["code"] == "unsupported_source"


def test_create_job_requires_authorization_and_valid_url(monkeypatch):
    r = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ", "authorized": False})
    assert r.status_code == 400
    r = client.post("/api/jobs", json={"url": "https://example.com/v", "authorized": True})
    assert r.status_code == 422
    r = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ", "authorized": True,
                                       "options": {"max_clip_seconds": 90}})
    assert r.status_code == 422  # clips can never exceed 60 s


def test_job_404s():
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    assert client.get("/api/jobs/../../etc").status_code == 404


def test_youtube_job_reports_clear_error_when_unreachable(monkeypatch):
    """Simulate YouTube being unreachable: the job must fail with a readable message, not hang or crash."""
    from app.ingest import youtube
    from app.ingest.base import IngestError

    def boom(self, url):
        raise IngestError("This video is private. Only public videos can be processed.", "video_private")

    monkeypatch.setattr(youtube.YouTubeProvider, "fetch_metadata", boom)
    r = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ", "authorized": True})
    assert r.status_code == 201
    job = _wait(r.json()["id"], timeout=30)
    assert job["status"] == "failed"
    assert job["error_code"] == "video_private"
    assert "private" in job["error"]


def _wait(job_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in {"completed", "failed", "cancelled"} and not any(c["status"] in {"pending", "rendering"} for c in j["clips"]):
            return j
        time.sleep(0.5)
    raise AssertionError("job did not finish in time")


@needs_ffmpeg
@pytest.mark.slow
def test_demo_end_to_end():
    r = client.post("/api/demo", json={"max_clips": 3, "render": {"layout": "blur"}})
    assert r.status_code == 201
    job = _wait(r.json()["id"])
    assert job["status"] == "completed", job.get("error")
    assert job["is_demo"] and job["source"]["is_sample"] and "SAMPLE" in job["source"]["title"]
    clips = job["clips"]
    assert 1 <= len(clips) <= 3
    for c in clips:
        assert c["status"] == "ready"
        assert c["end"] - c["start"] <= 60 and c["rendered_duration"] <= 60.1
        assert (c["output_width"], c["output_height"]) == (720, 1280)
        assert c["captions"]
    jid, cid = job["id"], clips[0]["id"]

    v = client.get(f"/api/jobs/{jid}/clips/{cid}/video")
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4" and len(v.content) > 10_000
    d = client.get(f"/api/jobs/{jid}/clips/{cid}/video", params={"download": True})
    assert "attachment" in d.headers["content-disposition"]
    assert client.get(f"/api/jobs/{jid}/clips/{cid}/video", headers={"Range": "bytes=0-99"}).status_code == 206
    assert client.get(f"/api/jobs/{jid}/clips/{cid}/thumbnail").status_code == 200

    # edit: invalid (>60s) rejected; valid edit re-renders with new bounds and rebuilt captions
    c0 = clips[0]
    assert client.patch(f"/api/jobs/{jid}/clips/{cid}", json={"start": c0["start"], "end": c0["start"] + 61}).status_code == 422
    r = client.patch(f"/api/jobs/{jid}/clips/{cid}", json={"start": c0["start"], "end": c0["start"] + 12})
    assert r.status_code == 200
    job = _wait(jid)
    edited = next(c for c in job["clips"] if c["id"] == cid)
    assert edited["status"] == "ready" and abs(edited["rendered_duration"] - 12) < 0.3 and edited["version"] == 2
    assert all(cap["end"] <= 12.01 for cap in edited["captions"])

    # caption text edit
    caps = edited["captions"]
    caps[0]["text"] = "EDITED CAPTION"
    r = client.patch(f"/api/jobs/{jid}/clips/{cid}", json={"captions": caps})
    job = _wait(jid)
    assert next(c for c in job["clips"] if c["id"] == cid)["captions"][0]["text"] == "EDITED CAPTION"

    # zip
    z = client.get(f"/api/jobs/{jid}/download.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "clips.txt" in names and sum(n.endswith(".mp4") for n in names) == len(job["clips"])

    # delete a clip, then the job
    if len(job["clips"]) > 1:
        r = client.delete(f"/api/jobs/{jid}/clips/{job['clips'][-1]['id']}")
        assert len(r.json()["clips"]) == len(job["clips"]) - 1
    assert client.delete(f"/api/jobs/{jid}").status_code == 204
    assert client.get(f"/api/jobs/{jid}").status_code == 404


def test_cleanup_endpoint():
    r = client.post("/api/cleanup", params={"older_than_hours": 1000})
    assert r.status_code == 200 and "disk_usage_bytes" in r.json()
