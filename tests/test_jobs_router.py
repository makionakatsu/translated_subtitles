"""Integration test: the /api/jobs router with a stubbed pipeline.

We monkey-patch :func:`apps.api.services.transcribe_service.run_pipeline` so the
test exercises only the FastAPI plumbing — request shape, background task
lifecycle, SSE event stream, status transitions.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.backends.base import (
    Segment,
    TranscribeInfo,
    WhisperBackend,
)
from apps.api.main import app
from apps.api.routers import jobs as jobs_router
from apps.api.services.transcribe_service import TranscribeRequest, TranscribeResult
from apps.api.store import jobs as job_store
from apps.api.workers.progress import emit


class _StubBackend(WhisperBackend):
    name = "stub"

    def transcribe(self, audio_path, options):  # type: ignore[override]
        return [], TranscribeInfo(language="en", language_probability=1.0)


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch: pytest.MonkeyPatch) -> None:
    job_store.reset_store()
    monkeypatch.setattr(jobs_router, "select_backend", lambda *_a, **_k: _StubBackend())


@pytest.fixture
def fake_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    srt = out_dir / "demo.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n\n", encoding="utf-8")

    def _fake(request: TranscribeRequest, *, job_id, backend, translator, reporter, work_dir=None):
        emit(reporter, stage="download", pct=50, msg="halfway")
        emit(reporter, stage="transcribe", pct=100, msg="done")
        emit(reporter, stage="write", pct=100, msg="ok")
        return TranscribeResult(
            job_id=job_id,
            video_path=None,
            audio_path=None,
            segments=[Segment(start=0.0, end=1.0, text="hello")],
            info=TranscribeInfo(language="en", language_probability=1.0),
            outputs={"srt": srt},
        )

    monkeypatch.setattr(jobs_router, "run_pipeline", _fake)
    return srt


def test_create_job_runs_to_completion(fake_pipeline: Path) -> None:
    client = TestClient(app)

    resp = client.post(
        "/api/jobs",
        json={
            "source": "/tmp/anything.mp4",
            "formats": ["srt"],
        },
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]

    # Poll until completed (the in-process task should finish very quickly)
    for _ in range(50):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in ("completed", "failed"):
            break
        asyncio.run(asyncio.sleep(0.02))
    assert status["status"] == "completed", status
    assert status["outputs"] == {"srt": str(fake_pipeline)}


def test_download_output_returns_file(fake_pipeline: Path) -> None:
    client = TestClient(app)
    resp = client.post("/api/jobs", json={"source": "/tmp/anything.mp4", "formats": ["srt"]})
    job_id = resp.json()["id"]
    for _ in range(50):
        if client.get(f"/api/jobs/{job_id}").json()["status"] == "completed":
            break
        asyncio.run(asyncio.sleep(0.02))
    dl = client.get(f"/api/jobs/{job_id}/outputs/srt")
    assert dl.status_code == 200
    assert b"hello" in dl.content


def test_translation_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(app)
    resp = client.post(
        "/api/jobs",
        json={"source": "/tmp/anything.mp4", "target_lang": "ja", "formats": ["srt"]},
    )
    assert resp.status_code == 400
    assert "GEMINI_API_KEY" in resp.json()["detail"]
