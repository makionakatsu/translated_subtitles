import shutil
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.services.storage as storage

    storage.PROJECTS_DIR = tmp_path / "projects"
    return TestClient(app)


def make_sample_video(path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_preflight(client):
    response = client.get("/api/preflight")
    assert response.status_code == 200
    names = {check["name"] for check in response.json()["checks"]}
    assert {"ffmpeg", "ffprobe", "projects_writable", "gemini_api_key", "yt_dlp"}.issubset(names)
    assert {
        "python_executable",
        "python_version",
        "apple_silicon",
        "mlx",
        "mlx_whisper",
        "asr_engine",
        "asr_backend_mlx",
        "asr_backend_faster-whisper",
    }.issubset(names)


def test_gemini_key_settings(client, tmp_path, monkeypatch):
    import app.services.secrets as secrets

    secret_file = tmp_path / "secrets.json"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "SECRET_DIR", tmp_path)
    monkeypatch.setattr(secrets, "SECRET_FILE", secret_file)
    monkeypatch.setattr(secrets, "_keychain_available", lambda: False)

    assert client.get("/api/settings").json()["gemini_api_key"]["configured"] is False
    saved = client.post("/api/settings/gemini-key", json={"api_key": "abc"}).json()
    assert saved["gemini_api_key"]["configured"] is True
    assert client.get("/api/settings").json()["gemini_api_key"]["configured"] is True
    assert client.delete("/api/settings/gemini-key").json()["gemini_api_key"]["configured"] is False


def test_create_project_from_local_path(client, tmp_path):
    video = tmp_path / "sample video.mp4"
    make_sample_video(video)
    response = client.post("/api/projects", data={"local_path": str(video)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project"]["metadata"]["has_video"] is True
    assert data["project"]["metadata"]["has_audio"] is True
    assert client.get(f"/api/projects/{data['project_id']}").status_code == 200
    assert client.get(f"/api/projects/{data['project_id']}/video").status_code == 200


def test_create_project_from_url_uses_downloader(client, tmp_path, monkeypatch):
    downloaded = tmp_path / "downloaded.mp4"
    make_sample_video(downloaded)

    def fake_download_url(url, out_dir):
        assert url == "https://example.com/video"
        target = out_dir / "source.mp4"
        target.write_bytes(downloaded.read_bytes())
        return target

    monkeypatch.setattr("app.main.download_url", fake_download_url)
    response = client.post("/api/projects", data={"local_path": "https://example.com/video"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project"]["video_name"] == "source.mp4"
    assert data["project"]["metadata"]["has_video"] is True


def test_create_project_rejects_missing_path(client):
    response = client.post("/api/projects", data={"local_path": "/not/here.mp4"})
    assert response.status_code == 400


def test_render_subtitles_endpoint(client, tmp_path):
    video = tmp_path / "sample.mp4"
    make_sample_video(video)
    created = client.post("/api/projects", data={"local_path": str(video)}).json()
    project_id = created["project_id"]
    patch = [
        {
            "id": 1,
            "start_ms": 0,
            "end_ms": 1000,
            "display_text": "hello",
            "locked": False,
        }
    ]
    # Directly seed one segment through storage because ASR is intentionally not used in API smoke tests.
    from app.models import CaptionSegment
    from app.services.storage import load_project, save_project

    project = load_project(project_id)
    project.segments = [CaptionSegment(id=1, start_ms=0, end_ms=1000, source_text="hello", display_text="hello")]
    save_project(project)
    assert client.patch(f"/api/projects/{project_id}/segments", json=patch).status_code == 200
    response = client.post(f"/api/projects/{project_id}/render", json={"outputs": ["ass", "srt", "vtt", "bilingual_ass"]})
    assert response.status_code == 200, response.text
    artifacts = response.json()["artifacts"]
    assert "ass_path" in artifacts
    assert "srt_path" in artifacts
    assert "vtt_path" in artifacts
    assert "bilingual_ass_path" in artifacts


def test_segment_split_and_merge(client, tmp_path):
    video = tmp_path / "sample.mp4"
    make_sample_video(video)
    created = client.post("/api/projects", data={"local_path": str(video)}).json()
    project_id = created["project_id"]
    from app.models import CaptionSegment
    from app.services.storage import load_project, save_project

    project = load_project(project_id)
    project.segments = [CaptionSegment(id=1, start_ms=0, end_ms=2000, source_text="hello world", display_text="hello world")]
    save_project(project)

    split = client.post(f"/api/projects/{project_id}/segments/1/split", json={"at_ms": 1000})
    assert split.status_code == 200, split.text
    assert len(split.json()["project"]["segments"]) == 2

    merged = client.post(f"/api/projects/{project_id}/segments/1/merge-next")
    assert merged.status_code == 200, merged.text
    segments = merged.json()["project"]["segments"]
    assert len(segments) == 1
    assert segments[0]["start_ms"] == 0
    assert segments[0]["end_ms"] == 2000


def test_translate_rejects_empty_project(client, tmp_path):
    video = tmp_path / "sample.mp4"
    make_sample_video(video)
    created = client.post("/api/projects", data={"local_path": str(video)}).json()
    response = client.post(f"/api/projects/{created['project_id']}/translate", json={"target_lang": "ja"})
    assert response.status_code == 400
    assert "文字起こし" in response.json()["detail"]


def test_render_rejects_empty_project(client, tmp_path):
    video = tmp_path / "sample.mp4"
    make_sample_video(video)
    created = client.post("/api/projects", data={"local_path": str(video)}).json()
    response = client.post(f"/api/projects/{created['project_id']}/render", json={"outputs": ["ass", "srt", "mp4"]})
    assert response.status_code == 400
    assert "文字起こし" in response.json()["detail"]


def test_translation_decision():
    assert main_module.translation_decision("en", "ja")["translate"] is True
    assert main_module.translation_decision("ja", "ja")["translate"] is False
    assert main_module.translation_decision("auto", "none")["translate"] is False
    assert main_module.translation_decision("auto", "ja")["translate"] is True


def test_generate_endpoint_runs_asr_and_translation(client, tmp_path, monkeypatch):
    video = tmp_path / "sample.mp4"
    make_sample_video(video)
    created = client.post("/api/projects", data={"local_path": str(video)}).json()
    project_id = created["project_id"]
    updates = []

    class DummyContext:
        def check_cancel(self):
            return None

        async def update(self, progress, message, **kwargs):
            updates.append({"progress": progress, "message": message, **kwargs})

    async def submit(kind, project_id_arg, func):
        assert kind == "generate"
        assert project_id_arg == project_id
        await func(DummyContext())
        return SimpleNamespace(id="job-generate")

    def fake_extract_audio(video_path, audio_path, cancel_check=None):
        audio_path.write_bytes(b"audio")
        return audio_path

    def fake_transcribe(audio_path, preset, source_lang, asr_engine):
        info = SimpleNamespace(language="en", asr_engine="mlx", asr_model="fake", asr_device="mlx", asr_duration_sec=0.1)
        return [{"start": 0.0, "end": 1.0, "text": "hello world", "words": []}], info, {"asr_sec": 0.1}

    def fake_translate_project(project, target_lang, api_key=None, progress=None):
        if progress:
            progress(100, "翻訳完了", 1, 1)
        for segment in project.segments:
            segment.translated_text = "こんにちは世界"
            segment.display_text = "こんにちは世界"
        project.translation_batches = [{"batch_index": 1, "count": len(project.segments), "engine": "gemini", "error": None}]
        return project

    monkeypatch.setattr(main_module.job_manager, "submit", submit)
    monkeypatch.setattr(main_module, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(main_module.asr, "transcribe", fake_transcribe)
    monkeypatch.setattr(main_module.asr, "selected_backend_name", lambda engine: "mlx")
    monkeypatch.setattr(main_module.asr, "model_for_request", lambda preset, engine: "fake")
    monkeypatch.setattr(main_module, "translate_project", fake_translate_project)

    response = client.post(
        f"/api/projects/{project_id}/generate",
        json={"preset": "fast", "source_lang": "auto", "target_lang": "ja", "asr_engine": "auto", "translate_mode": "auto"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == "job-generate"

    project = client.get(f"/api/projects/{project_id}").json()["project"]
    assert project["segments"][0]["translated_text"] == "こんにちは世界"
    assert project["translation_summary"]["translated"] == 1
    assert project["generation_status"]["stage"] == "done"
    assert any(update.get("stage") == "translate" for update in updates)
