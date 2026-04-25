"""Smoke test for backend selection and the FasterWhisper adapter."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from apps.api.backends import base


def test_select_backend_falls_back_to_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    backend = base.select_backend("auto")
    assert backend.name == "faster_whisper"


def test_select_backend_explicit_mlx(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = base.select_backend("mlx")
    assert backend.name == "mlx"


def test_faster_whisper_backend_calls_underlying_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Build a tiny stub that mimics the faster_whisper API contract.
    class _Word:
        def __init__(self, start: float, end: float, word: str) -> None:
            self.start = start
            self.end = end
            self.word = word
            self.probability = 0.95

    class _Segment:
        def __init__(self) -> None:
            self.start = 0.0
            self.end = 1.0
            self.text = "hi"
            self.words = [_Word(0.0, 1.0, "hi")]
            self.avg_logprob = -0.3
            self.no_speech_prob = 0.05

    class _Info:
        language = "en"
        language_probability = 0.99
        duration = 1.0

    class _Model:
        def __init__(self, *a, **kw):
            self.calls: list[dict[str, object]] = []

        def transcribe(self, *a, **kw):
            self.calls.append(kw)
            return iter([_Segment()]), _Info()

    fw_stub = types.ModuleType("faster_whisper")
    fw_stub.WhisperModel = _Model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fw_stub)

    from apps.api.backends.faster_whisper import FasterWhisperBackend

    backend = FasterWhisperBackend()
    segs, info = backend.transcribe(
        Path("/tmp/x.wav"),
        base.TranscribeOptions(model="medium"),
    )
    assert info.language == "en"
    assert len(segs) == 1
    assert segs[0].text == "hi"
    assert segs[0].words[0].text == "hi"
