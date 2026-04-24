import sys
from types import SimpleNamespace

import pytest

from app.services import asr


def test_normalize_mlx_segments_maps_words():
    result = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "hello",
                "words": [{"start": 0.0, "end": 0.5, "text": "hello"}],
            }
        ]
    }
    normalized = asr.normalize_mlx_segments(result)
    assert normalized == [{"start": 0.0, "end": 1.0, "text": "hello", "words": [{"start": 0.0, "end": 0.5, "word": "hello"}]}]


def test_select_backend_prefers_mlx(monkeypatch):
    monkeypatch.setattr(asr.BACKENDS["mlx"], "available", lambda: True)
    monkeypatch.setattr(asr.BACKENDS["faster-whisper"], "available", lambda: True)
    assert asr.select_backend("auto").name == "mlx"


def test_select_backend_falls_back_to_faster(monkeypatch):
    monkeypatch.setattr(asr.BACKENDS["mlx"], "available", lambda: False)
    monkeypatch.setattr(asr.BACKENDS["faster-whisper"], "available", lambda: True)
    assert asr.select_backend("auto").name == "faster-whisper"


def test_explicit_unavailable_backend_fails(monkeypatch):
    monkeypatch.setattr(asr.BACKENDS["mlx"], "available", lambda: False)
    with pytest.raises(asr.ASRError):
        asr.select_backend("mlx")


def test_auto_transcribe_falls_back_when_mlx_raises(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    def fail_mlx(audio_path, preset, source_lang):
        raise RuntimeError("mlx failed")

    def ok_faster(audio_path, preset, source_lang):
        return [], SimpleNamespace(language="en", asr_engine="faster-whisper", asr_model="small", asr_device="cpu", asr_duration_sec=0.1), {"asr_sec": 0.1}

    monkeypatch.setattr(asr.BACKENDS["mlx"], "available", lambda: True)
    monkeypatch.setattr(asr.BACKENDS["mlx"], "transcribe", fail_mlx)
    monkeypatch.setattr(asr.BACKENDS["faster-whisper"], "available", lambda: True)
    monkeypatch.setattr(asr.BACKENDS["faster-whisper"], "transcribe", ok_faster)

    _, info, timings = asr.transcribe(str(audio), asr_engine="auto")

    assert info.asr_engine == "faster-whisper"
    assert timings["asr_sec"] == 0.1


def test_mlx_transcribe_passes_subtitle_safe_options(monkeypatch, tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    calls = {}

    def fake_transcribe(audio_path, **kwargs):
        calls["audio_path"] = audio_path
        calls["kwargs"] = kwargs
        return {
            "language": "en",
            "duration": 1.0,
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello", "words": []}],
        }

    monkeypatch.setattr(asr, "is_apple_silicon", lambda: True)
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=fake_transcribe))

    segments, info, timings = asr.MlxWhisperBackend().transcribe(str(audio), "fast", "en")

    assert segments[0]["text"] == "hello"
    assert calls["audio_path"] == str(audio)
    assert calls["kwargs"]["word_timestamps"] is True
    assert calls["kwargs"]["condition_on_previous_text"] is False
    assert calls["kwargs"]["language"] == "en"
    assert info.asr_engine == "mlx"
    assert timings["asr_rtf"] >= 0
