"""Whisper backend abstraction.

Two concrete backends ship in-tree:

* :class:`apps.api.backends.mlx.MLXBackend` — Apple Silicon native, the default
  on Mac. Built on `mlx-whisper`_, with word-level timestamps enabled.
* :class:`apps.api.backends.faster_whisper.FasterWhisperBackend` — CPU/CUDA
  fallback used by CI Linux and any non-Mac environment.

The protocol is intentionally minimal. Higher-level orchestration (VAD,
chunking, hallucination filtering, progress reporting) lives in
``apps/api/services/transcribe_service.py``.

.. _mlx-whisper: https://pypi.org/project/mlx-whisper/
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class Word:
    start: float
    end: float
    text: str
    prob: float = 1.0


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    speaker: str | None = None


@dataclass(slots=True)
class TranscribeInfo:
    language: str
    language_probability: float
    duration: float | None = None


@dataclass(slots=True)
class TranscribeOptions:
    """Parameters that travel through every backend.

    Defaults are tuned to suppress hallucinations per the audit findings:
    https://arxiv.org/html/2501.11378v1
    """

    model: str = "large-v3-turbo"
    language: str | None = None  # auto-detect when None
    beam_size: int = 5
    word_timestamps: bool = True
    condition_on_previous_text: bool = True
    temperature: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    initial_prompt: str | None = None
    vad_filter: bool = True


class WhisperBackend(ABC):
    """Concrete backends translate :class:`TranscribeOptions` into their native call."""

    name: str = "abstract"

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        options: TranscribeOptions,
    ) -> tuple[list[Segment], TranscribeInfo]:
        """Synchronously transcribe a 16 kHz mono WAV.

        Backends are wrapped with ``run_in_executor`` by the service layer; do
        not introduce asyncio inside concrete implementations unless the
        underlying library is genuinely async.
        """


def select_backend(prefer: Literal["mlx", "faster_whisper", "auto"] = "auto") -> WhisperBackend:
    """Return the best available backend for the current platform.

    On Apple Silicon we try ``mlx`` first; otherwise ``faster_whisper``. The
    ``auto`` default is resolved lazily so unit tests can monkey-patch import
    order.
    """
    import platform
    import sys

    is_mac_arm = sys.platform == "darwin" and platform.machine() == "arm64"

    candidates: list[Literal["mlx", "faster_whisper"]]
    if prefer == "auto":
        candidates = ["mlx", "faster_whisper"] if is_mac_arm else ["faster_whisper"]
    else:
        candidates = [prefer]

    last_err: Exception | None = None
    for name in candidates:
        try:
            if name == "mlx":
                from .mlx import MLXBackend

                return MLXBackend()
            from .faster_whisper import FasterWhisperBackend

            return FasterWhisperBackend()
        except ImportError as e:  # backend deps not installed
            last_err = e
            continue
    raise RuntimeError(
        "No Whisper backend available. Install with `uv sync --extra mac` (Apple "
        f"Silicon) or `uv sync --extra cpu` (Linux/CI). Last error: {last_err}"
    )
