from types import SimpleNamespace

from app.models import CaptionProject, CaptionSegment, VideoMetadata
from app.services.quality import apply_quality
from app.services.segmenter import build_segments, wrap_display_text


def test_segmenter_falls_back_without_words():
    raw = [SimpleNamespace(start=0.0, end=1.5, text="Hello world.")]
    segments = build_segments(raw, "en")
    assert len(segments) == 1
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 1500
    assert segments[0].display_text == "Hello world."


def test_segmenter_repairs_word_overlap():
    raw = [
        SimpleNamespace(
            words=[
                SimpleNamespace(start=0.0, end=1.2, word="Hello."),
                SimpleNamespace(start=1.19, end=2.0, word=" Again."),
            ]
        )
    ]
    segments = build_segments(raw, "en")
    assert all(segment.end_ms > segment.start_ms for segment in segments)


def test_japanese_wrap_limits_lines():
    text = "これはとても長い日本語字幕のテストです。画面からはみ出さないようにします。"
    wrapped = wrap_display_text(text, "ja")
    assert len(wrapped.splitlines()) <= 2


def test_quality_flags_bad_segments():
    project = CaptionProject(
        id="p",
        video_path="/tmp/v.mp4",
        video_name="v.mp4",
        metadata=VideoMetadata(width=720, height=1280, duration_ms=3000),
        target_lang="ja",
        segments=[
            CaptionSegment(id=1, start_ms=1000, end_ms=500, source_text="", display_text=""),
            CaptionSegment(id=2, start_ms=400, end_ms=900, source_text="hello", display_text="hello"),
        ],
    )
    apply_quality(project)
    assert "EMPTY_TEXT" in project.segments[0].warnings
    assert "INVALID_TIME" in project.segments[0].warnings
    assert "TOO_SHORT" in project.segments[1].warnings
