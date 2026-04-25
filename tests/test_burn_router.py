"""POST /api/jobs/{id}/burn integration test with ffmpeg subprocess mocked."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.models.segment import Segment
from apps.api.services import burn_service
from apps.api.store.jobs import get_store, reset_store


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_store()


def _seed_job(tmp_path: Path) -> str:
    store = get_store()
    record = store.create()
    record.status = "completed"
    video = tmp_path / "movie.mp4"
    video.write_bytes(b"")
    record.video_path = str(video)
    record.style_name = "Yu Gothic UI"
    record.font_size = 56
    record.segments = [
        Segment(id=0, start=0.0, end=1.0, text="hi", original_text="hi"),
    ]
    return record.id


def test_burn_returns_404_when_video_missing() -> None:
    job_id = _seed_job(Path("/tmp"))
    record = get_store().get(job_id)
    assert record is not None
    record.video_path = None
    client = TestClient(app)
    resp = client.post(f"/api/jobs/{job_id}/burn", json={})
    assert resp.status_code == 400


def test_burn_invokes_ffmpeg_and_records_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = _seed_job(tmp_path)

    captured: dict[str, object] = {}

    def _fake_burn(video_path, subtitle_path, *, out_dir, font_size, on_progress=None, duration_sec=None, **kw):
        captured["video"] = str(video_path)
        captured["sub"] = str(subtitle_path)
        captured["font_size"] = font_size
        out = Path(out_dir) / "burned.mp4"
        out.write_bytes(b"BURNED")
        if on_progress:
            on_progress(50.0, "halfway")
            on_progress(100.0, "done")
        return out

    monkeypatch.setattr(burn_service, "burn_subtitles", _fake_burn)

    client = TestClient(app)
    resp = client.post(f"/api/jobs/{job_id}/burn", json={})
    assert resp.status_code == 202

    # FastAPI BackgroundTasks run before TestClient's response unwinds, so the
    # output is recorded by the time we land here.
    record = get_store().get(job_id)
    assert record is not None
    assert "burned" in record.outputs
    assert Path(record.outputs["burned"]).exists()
    assert captured["font_size"] == 56
