"""Editor-facing endpoints: /api/jobs/{id}/segments CRUD + retranslate."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.models.segment import Segment
from apps.api.store.jobs import get_store, reset_store


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_store()


def _seed_completed_job(tmp_path: Path) -> str:
    """Create a JobRecord with two pre-canned segments and a fake SRT output."""
    store = get_store()
    record = store.create()
    record.status = "completed"
    record.source_language = "en"
    record.target_language = "ja"
    record.segments = [
        Segment(id=0, start=0.0, end=1.5, text="Hello", original_text="Hello"),
        Segment(id=1, start=1.5, end=3.0, text="World", original_text="World"),
    ]
    out = tmp_path / f"{record.id}.srt"
    out.write_text("legacy", encoding="utf-8")
    record.outputs = {"srt": out}
    return record.id


def test_get_segments_returns_full_payload(tmp_path: Path) -> None:
    job_id = _seed_completed_job(tmp_path)
    client = TestClient(app)
    resp = client.get(f"/api/jobs/{job_id}/segments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["source_language"] == "en"
    assert len(body["segments"]) == 2
    assert body["segments"][0]["text"] == "Hello"


def test_patch_segments_updates_in_place(tmp_path: Path) -> None:
    job_id = _seed_completed_job(tmp_path)
    client = TestClient(app)
    resp = client.patch(
        f"/api/jobs/{job_id}/segments",
        json={"edits": {"0": {"text": "こんにちは", "end": 1.6}}},
    )
    assert resp.status_code == 200
    body = resp.json()
    seg0 = next(s for s in body["segments"] if s["id"] == 0)
    assert seg0["text"] == "こんにちは"
    assert seg0["end"] == 1.6
    # The other segment is untouched.
    seg1 = next(s for s in body["segments"] if s["id"] == 1)
    assert seg1["text"] == "World"


def test_regenerate_outputs_rewrites_files_with_edits(tmp_path: Path) -> None:
    job_id = _seed_completed_job(tmp_path)
    client = TestClient(app)
    client.patch(
        f"/api/jobs/{job_id}/segments",
        json={"edits": {"0": {"text": "EDITED"}}},
    )
    resp = client.post(f"/api/jobs/{job_id}/regenerate")
    assert resp.status_code == 200
    body = resp.json()
    srt_path = Path(body["srt"])
    contents = srt_path.read_text(encoding="utf-8")
    assert "EDITED" in contents
    # Old "World" should still be there for segment 1.
    assert "World" in contents
    # The legacy placeholder should be gone.
    assert "legacy" not in contents


def test_retranslate_requires_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    job_id = _seed_completed_job(tmp_path)
    client = TestClient(app)
    resp = client.post(
        f"/api/jobs/{job_id}/segments/0/retranslate",
        json={"candidates": 3},
    )
    assert resp.status_code == 400
    assert "GEMINI_API_KEY" in resp.json()["detail"]


def test_retranslate_returns_unique_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    from apps.api.services import translate_service

    def _fake(self, text, **kwargs):  # type: ignore[no-untyped-def]
        return ["案A", "案B", "案A", "案C"]  # duplicate is filtered

    monkeypatch.setattr(translate_service.GeminiTranslator, "retranslate_one", _fake)

    job_id = _seed_completed_job(tmp_path)
    client = TestClient(app)
    resp = client.post(
        f"/api/jobs/{job_id}/segments/0/retranslate",
        json={"candidates": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["candidates"] == ["案A", "案B", "案A", "案C"]
