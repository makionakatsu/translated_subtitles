"""faster-whisper backend (CI / Linux / CUDA fallback).

This backend is optional. Install with ``uv sync --extra cpu``.
"""
from __future__ import annotations

from pathlib import Path

from .base import Segment, TranscribeInfo, TranscribeOptions, WhisperBackend, Word


class FasterWhisperBackend(WhisperBackend):
    name = "faster_whisper"

    def __init__(
        self,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        # Lazy import so the package is only required when this backend is used.
        from faster_whisper import WhisperModel  # noqa: F401  (import-time check)

        self._device = device
        self._compute_type = compute_type
        self._model_cache: dict[str, object] = {}

    def _get_model(self, model_size: str) -> object:
        from faster_whisper import WhisperModel

        key = f"{model_size}|{self._device}|{self._compute_type}"
        if key not in self._model_cache:
            self._model_cache[key] = WhisperModel(
                model_size, device=self._device, compute_type=self._compute_type
            )
        return self._model_cache[key]

    def transcribe(
        self,
        audio_path: Path,
        options: TranscribeOptions,
    ) -> tuple[list[Segment], TranscribeInfo]:
        model = self._get_model(options.model)
        segments_iter, info = model.transcribe(  # type: ignore[attr-defined]
            str(audio_path),
            language=options.language,
            beam_size=options.beam_size,
            word_timestamps=options.word_timestamps,
            condition_on_previous_text=options.condition_on_previous_text,
            temperature=options.temperature,
            compression_ratio_threshold=options.compression_ratio_threshold,
            log_prob_threshold=options.log_prob_threshold,
            no_speech_threshold=options.no_speech_threshold,
            initial_prompt=options.initial_prompt,
            vad_filter=options.vad_filter,
        )

        segments: list[Segment] = []
        for s in segments_iter:
            words = [
                Word(start=w.start, end=w.end, text=w.word, prob=getattr(w, "probability", 1.0))
                for w in (getattr(s, "words", None) or [])
            ]
            segments.append(
                Segment(
                    start=s.start,
                    end=s.end,
                    text=s.text,
                    words=words,
                    avg_logprob=getattr(s, "avg_logprob", None),
                    no_speech_prob=getattr(s, "no_speech_prob", None),
                )
            )
        return segments, TranscribeInfo(
            language=info.language,
            language_probability=info.language_probability,
            duration=getattr(info, "duration", None),
        )
