"""End-to-end pipeline tests with stub backend, ffmpeg conversion mocked.

The pipeline calls ``media_service.convert_to_wav``, ``download_video``, and
``get_video_resolution`` — all of which can hit ffmpeg/yt-dlp on real systems.
We monkey-patch them to keep the test hermetic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.backends.base import (
    Segment,
    TranscribeInfo,
    TranscribeOptions,
    WhisperBackend,
)
from apps.api.services import media_service
from apps.api.services.transcribe_service import (
    TranscribeRequest,
    TranscribeResult,
    run_pipeline,
)
from apps.api.workers.progress import CollectingReporter


class _RecordingBackend(WhisperBackend):
    name = "recording"

    def __init__(self, segs: list[Segment]) -> None:
        self.segs = segs
        self.audio_path: Path | None = None
        self.options: TranscribeOptions | None = None

    def transcribe(self, audio_path, options):  # type: ignore[override]
        self.audio_path = audio_path
        self.options = options
        return self.segs, TranscribeInfo(language="en", language_probability=1.0)


@pytest.fixture
def fake_media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Create a fake audio file and stub conversion / probing."""
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"RIFFsilent")

    def _convert(input_path, output_path):  # type: ignore[no-untyped-def]
        Path(output_path).write_bytes(b"RIFFcompressed")
        return Path(output_path)

    monkeypatch.setattr(media_service, "convert_to_wav", _convert)
    monkeypatch.setattr(media_service, "get_video_resolution", lambda p: (1920, 1080))
    monkeypatch.setattr(media_service, "get_video_metadata", lambda p: {"width": 1920, "height": 1080, "duration": 10.0, "frame_rate": 24.0})
    return audio


def test_pipeline_writes_srt_only(fake_media: Path, tmp_path: Path) -> None:
    backend = _RecordingBackend(
        [
            Segment(start=0.0, end=1.0, text="hello"),
            Segment(start=1.0, end=2.5, text="world"),
        ]
    )
    reporter = CollectingReporter()
    result: TranscribeResult = run_pipeline(
        TranscribeRequest(
            source=str(fake_media),
            target_lang=None,
            formats=("srt",),
            output_dir=tmp_path / "out",
        ),
        job_id="t1",
        backend=backend,
        reporter=reporter,
        work_dir=tmp_path / "work",
    )
    assert "srt" in result.outputs
    body = result.outputs["srt"].read_text(encoding="utf-8")
    assert "hello" in body and "world" in body
    # Stages are reported in order.
    stages = [e.stage for e in reporter.events]
    assert stages.index("download") < stages.index("transcribe") < stages.index("write")


def test_pipeline_skips_conversion_for_wav(fake_media: Path, tmp_path: Path) -> None:
    backend = _RecordingBackend([Segment(start=0.0, end=1.0, text="ok")])
    reporter = CollectingReporter()
    run_pipeline(
        TranscribeRequest(source=str(fake_media), formats=("srt",), output_dir=tmp_path / "out"),
        job_id="t2",
        backend=backend,
        reporter=reporter,
        work_dir=tmp_path / "work",
    )
    convert_msgs = [e.msg for e in reporter.events if e.stage == "convert"]
    assert any("skipping" in m.lower() for m in convert_msgs)
