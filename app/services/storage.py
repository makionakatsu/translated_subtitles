from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict

from app.models import CaptionProject, VideoMetadata, utc_now_iso


ROOT_DIR = Path(__file__).resolve().parents[2]
PROJECTS_DIR = Path(os.getenv("CAPTION_PROJECTS_DIR", ROOT_DIR / "projects"))


def ensure_projects_dir() -> Path:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    return PROJECTS_DIR


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?"<>|:]+', "_", name).strip()
    return cleaned or "source"


def new_project_id() -> str:
    return uuid.uuid4().hex[:12]


def project_dir(project_id: str) -> Path:
    return ensure_projects_dir() / project_id


def project_json_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def artifact_path(project_id: str, filename: str) -> Path:
    return project_dir(project_id) / filename


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def save_project(project: CaptionProject) -> CaptionProject:
    project.updated_at = utc_now_iso()
    data = project.model_dump() if hasattr(project, "model_dump") else project.dict()
    atomic_write_json(project_json_path(project.id), data)
    return project


def load_project(project_id: str) -> CaptionProject:
    path = project_json_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    with path.open("r", encoding="utf-8") as handle:
        return CaptionProject(**json.load(handle))


def create_project(video_path: Path, metadata: VideoMetadata) -> CaptionProject:
    project_id = new_project_id()
    project_dir(project_id).mkdir(parents=True, exist_ok=False)
    project = CaptionProject(
        id=project_id,
        video_path=str(video_path),
        video_name=video_path.name,
        metadata=metadata,
    )
    return save_project(project)


def write_upload(project_id: str, original_name: str, content: bytes) -> Path:
    suffix = Path(original_name).suffix or ".bin"
    path = artifact_path(project_id, f"source{suffix}")
    path.write_bytes(content)
    return path


def artifact_urls(project: CaptionProject) -> Dict[str, str]:
    urls: Dict[str, str] = {}
    for key, value in project.artifacts.items():
        if value:
            urls[key] = f"/api/projects/{project.id}/artifacts/{Path(value).name}"
    return urls
