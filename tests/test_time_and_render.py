from app.models import CaptionProject, CaptionSegment, VideoMetadata
from app.services.render import ass_escape, format_ass_time, format_srt_time, format_vtt_time, write_ass, write_bilingual_ass, write_srt, write_vtt


def test_srt_time_never_emits_1000_ms():
    assert format_srt_time(1996) == "00:00:01,996"
    assert ",1000" not in format_srt_time(1996)


def test_ass_time_carries_centiseconds():
    assert format_ass_time(1996) == "0:00:02.00"
    assert ".100" not in format_ass_time(1996)


def test_vtt_time_uses_dot_milliseconds():
    assert format_vtt_time(1996) == "00:00:01.996"


def test_ass_escape_blocks_override_tags():
    assert ass_escape("{\\pos(1,1)}hello\nworld") == "\\{\\pos(1,1)\\}hello\\Nworld"


def test_write_ass_and_srt(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTION_PROJECTS_DIR", str(tmp_path))
    project = CaptionProject(
        id="abc123",
        video_path="/tmp/video.mp4",
        video_name="video.mp4",
        metadata=VideoMetadata(width=1280, height=720, duration_ms=2000, has_video=True, has_audio=True),
        segments=[
            CaptionSegment(id=1, start_ms=0, end_ms=1996, source_text="hello", display_text="hello"),
        ],
    )
    # storage module reads env at import time; override the module global for this test.
    import app.services.storage as storage

    storage.PROJECTS_DIR = tmp_path
    project.segments[0].translated_text = "こんにちは"
    project.segments[0].display_text = "こんにちは"
    ass_path = write_ass(project)
    bilingual_ass_path = write_bilingual_ass(project)
    srt_path = write_srt(project)
    vtt_path = write_vtt(project)
    assert ass_path.exists()
    assert bilingual_ass_path.exists()
    assert srt_path.exists()
    assert vtt_path.exists()
    assert "PlayResX: 1280" in ass_path.read_text(encoding="utf-8")
    assert "hello\\Nこんにちは" in bilingual_ass_path.read_text(encoding="utf-8")
    assert "00:00:01,996" in srt_path.read_text(encoding="utf-8")
    assert "WEBVTT" in vtt_path.read_text(encoding="utf-8")
