"""mlx-whisper backend (Apple Silicon, default on Mac).

The ``model`` field of :class:`TranscribeOptions` is interpreted as a suffix on
the official MLX-community repo, e.g. ``large-v3-turbo`` resolves to
``mlx-community/whisper-large-v3-turbo``. Custom Hugging Face repos can be
specified verbatim if they contain a ``/``.
"""
from __future__ import annotations

from pathlib import Path

from .base import Segment, TranscribeInfo, TranscribeOptions, WhisperBackend, Word

_REPO_PREFIX = "mlx-community/whisper-"


def _resolve_repo(model: str) -> str:
    if "/" in model:
        return model
    return f"{_REPO_PREFIX}{model}"


class MLXBackend(WhisperBackend):
    name = "mlx"

    def __init__(self) -> None:
        # Lazy import so the package is only required when this backend is used.
        import mlx_whisper  # noqa: F401

    def transcribe(
        self,
        audio_path: Path,
        options: TranscribeOptions,
    ) -> tuple[list[Segment], TranscribeInfo]:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=_resolve_repo(options.model),
            language=options.language,
            word_timestamps=options.word_timestamps,
            condition_on_previous_text=options.condition_on_previous_text,
            temperature=options.temperature,
            compression_ratio_threshold=options.compression_ratio_threshold,
            logprob_threshold=options.log_prob_threshold,
            no_speech_threshold=options.no_speech_threshold,
            initial_prompt=options.initial_prompt,
        )

        segments: list[Segment] = []
        for s in result.get("segments", []):
            words = [
                Word(
                    start=float(w["start"]),
                    end=float(w["end"]),
                    text=str(w.get("word") or w.get("text") or ""),
                    prob=float(w.get("probability", 1.0)),
                )
                for w in (s.get("words") or [])
            ]
            segments.append(
                Segment(
                    start=float(s["start"]),
                    end=float(s["end"]),
                    text=str(s.get("text", "")),
                    words=words,
                    avg_logprob=s.get("avg_logprob"),
                    no_speech_prob=s.get("no_speech_prob"),
                )
            )
        return segments, TranscribeInfo(
            language=str(result.get("language", "")),
            language_probability=float(result.get("language_probability", 1.0)),
            duration=result.get("duration"),
        )
