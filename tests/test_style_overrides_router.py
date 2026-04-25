"""Tests for /api/jobs/{id}/style and /api/jobs/{id}/ass."""
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


def _seed_job() -> str:
    store = get_store()
    record = store.create()
    record.status = "completed"
    record.source_language = "en"
    record.target_language = "ja"
    record.style_name = "Yu Gothic UI"
    record.font_size = 56
    record.segments = [
        Segment(id=0, start=0.0, end=1.5, text="Hello", original_text="Hello"),
        Segment(id=1, start=2.0, end=3.5, text="こんにちは", original_text="Hello"),
    ]
    return record.id


def test_get_style_returns_initial(tmp_path: Path) -> None:
    job_id = _seed_job()
    client = TestClient(app)
    body = client.get(f"/api/jobs/{job_id}/style").json()
    assert body["style_name"] == "Yu Gothic UI"
    assert body["font_size"] == 56
    assert body["overrides"] == {}
    assert "Yu Gothic UI" in body["available_styles"]


def test_patch_style_merges_overrides() -> None:
    job_id = _seed_job()
    client = TestClient(app)
    r1 = client.patch(
        f"/api/jobs/{job_id}/style",
        json={"overrides": {"PrimaryColour": "&H0000FFFF"}, "font_size": 72},
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["font_size"] == 72
    assert body["overrides"]["PrimaryColour"] == "&H0000FFFF"

    # Second PATCH should merge, not replace.
    r2 = client.patch(
        f"/api/jobs/{job_id}/style",
        json={"overrides": {"Outline": "5"}},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["overrides"]["PrimaryColour"] == "&H0000FFFF"
    assert body["overrides"]["Outline"] == "5"


def test_get_ass_includes_segments_and_overrides() -> None:
    job_id = _seed_job()
    client = TestClient(app)
    client.patch(
        f"/api/jobs/{job_id}/style",
        json={"font_size": 72, "overrides": {"PrimaryColour": "&H0000FFFF"}},
    )
    r = client.get(f"/api/jobs/{job_id}/ass")
    assert r.status_code == 200
    text = r.text
    # Header reflects the override.
    assert "&H0000FFFF" in text
    assert "Style: Yu Gothic UI," in text
    # Body has both events.
    assert "Hello" in text
    assert "こんにちは" in text
    assert text.count("Dialogue:") == 2


def test_font_size_clamped() -> None:
    job_id = _seed_job()
    client = TestClient(app)
    body = client.patch(
        f"/api/jobs/{job_id}/style",
        json={"font_size": 9999},
    ).json()
    assert body["font_size"] == 400
    body = client.patch(
        f"/api/jobs/{job_id}/style",
        json={"font_size": -10},
    ).json()
    assert body["font_size"] == 8
