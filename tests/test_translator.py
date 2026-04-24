import pytest

from app.models import CaptionProject, CaptionSegment
from app.services.translator import BatchTranslation, format_srt_block, make_batches, ms_to_srt_timestamp, validate_translation_response
import app.services.secrets as secrets
import app.services.translator as translator


def test_make_batches_respects_count():
    segments = [CaptionSegment(id=i, source_text="hello", display_text="hello", start_ms=i, end_ms=i + 1000) for i in range(45)]
    batches = make_batches(segments, max_items=20, max_chars=6000)
    assert [len(batch) for batch in batches] == [20, 20, 5]


def test_srt_format_preserves_ids_and_timestamps():
    segment = CaptionSegment(id=7, source_text="hello", display_text="hello", start_ms=1999, end_ms=2501)
    assert ms_to_srt_timestamp(1999) == "00:00:01,999"
    block = format_srt_block([segment])
    assert "7" in block
    assert "00:00:01,999 --> 00:00:02,501" in block
    assert "hello" in block


def test_validate_translation_response_maps_ids():
    segments = [
        CaptionSegment(id=7, source_text="hello", display_text="hello", start_ms=0, end_ms=1000),
        CaptionSegment(id=8, source_text="world", display_text="world", start_ms=1000, end_ms=2000),
    ]
    result = validate_translation_response(
        '{"items":[{"segment_id":7,"translated_text":"こんにちは"},{"segment_id":8,"translated_text":"世界"}]}',
        segments,
    )
    assert result == {7: "こんにちは", 8: "世界"}


def test_validate_translation_response_rejects_missing_id():
    segments = [CaptionSegment(id=7, source_text="hello", display_text="hello", start_ms=0, end_ms=1000)]
    with pytest.raises(Exception):
        validate_translation_response('{"items":[{"segment_id":9,"translated_text":"x"}]}', segments)


def test_validate_translation_response_rejects_empty_text():
    segments = [CaptionSegment(id=7, source_text="hello", display_text="hello", start_ms=0, end_ms=1000)]
    with pytest.raises(Exception):
        validate_translation_response('{"items":[{"segment_id":7,"translated_text":""}]}', segments)


def test_secret_file_fallback_roundtrip(tmp_path, monkeypatch):
    secret_file = tmp_path / "secrets.json"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "SECRET_DIR", tmp_path)
    monkeypatch.setattr(secrets, "SECRET_FILE", secret_file)
    monkeypatch.setattr(secrets, "_keychain_available", lambda: False)

    source = secrets.save_gemini_api_key("  test-key  ")

    assert source == str(secret_file)
    assert secrets.load_gemini_api_key() == "test-key"
    assert oct(secret_file.stat().st_mode & 0o777) == "0o600"
    assert secrets.gemini_api_key_status()["configured"] is True
    secrets.delete_gemini_api_key()
    assert secrets.load_gemini_api_key() is None


def test_translate_project_uses_large_parallel_srt_batches(monkeypatch):
    segments = [
        CaptionSegment(id=i, source_text=f"text {i}", display_text=f"text {i}", start_ms=i * 1000, end_ms=i * 1000 + 900)
        for i in range(130)
    ]
    project = CaptionProject(id="p1", video_path="/tmp/video.mp4", video_name="video.mp4", source_lang="en", segments=segments)
    calls = []

    def fake_translate_batch(batch_index, batch, all_segments, source_lang, target_lang, api_key, model):
        calls.append((batch_index, len(batch), source_lang, target_lang))
        return BatchTranslation(
            batch_index=batch_index,
            count=len(batch),
            engine="gemini",
            translations={segment.id: f"訳 {segment.id}" for segment in batch},
        )

    monkeypatch.setattr(translator, "translate_batch_with_fallback", fake_translate_batch)
    monkeypatch.setattr(translator, "save_project", lambda project: project)

    translated = translator.translate_project(project, "ja", api_key="fake")

    assert [call[1] for call in sorted(calls)] == [120, 10]
    assert translated.segments[0].display_text == "訳 0"
    assert translated.segments[-1].display_text == "訳 129"
    assert [record["count"] for record in translated.translation_batches] == [120, 10]
