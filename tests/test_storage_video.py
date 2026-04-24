import json

import pytest

from app.models import CaptionProject, VideoMetadata
from app.services.storage import atomic_write_json, load_project, save_project
from app.services.video import parse_fps


def test_atomic_write_json(tmp_path):
    path = tmp_path / "project.json"
    atomic_write_json(path, {"hello": "world"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"hello": "world"}
    assert not path.with_suffix(".json.tmp").exists()


def test_save_and_load_project(tmp_path, monkeypatch):
    import app.services.storage as storage

    storage.PROJECTS_DIR = tmp_path
    project = CaptionProject(id="p1", video_path="/tmp/v.mp4", video_name="v.mp4", metadata=VideoMetadata())
    save_project(project)
    loaded = load_project("p1")
    assert loaded.id == "p1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("30000/1001", 29.97002997002997), ("24/1", 24.0), ("0/0", 0.0), ("bad", 0.0)],
)
def test_parse_fps(value, expected):
    assert parse_fps(value) == expected
