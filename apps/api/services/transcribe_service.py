"""High-level transcription orchestration.

Drives the full pipeline: ``download → wav → transcribe → (translate) → write``
through pluggable :class:`apps.api.backends.base.WhisperBackend` and
:class:`apps.api.services.translate_service.GeminiTranslator` instances, with a
:class:`apps.api.workers.progress.ProgressReporter` for SSE / WS fan-out.
"""
from __future__ import annotations

import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..backends.base import (
    Segment,
    TranscribeInfo,
    TranscribeOptions,
    WhisperBackend,
    select_backend,
)
from ..workers.progress import CollectingReporter, ProgressReporter, emit
from . import media_service, style_service, subtitle_service
from .translate_service import (
    GeminiTranslator,
    GlossaryEntry,
    TranslationResult,
    translate_in_place,
)

logger = logging.getLogger(__name__)

OutputFormat = Literal["srt", "ass", "fcpxml"]


@dataclass(slots=True)
class TranscribeRequest:
    """Single high-level request for the pipeline."""

    source: str  # URL or local path
    target_lang: str | None = None  # None = no translation
    formats: tuple[OutputFormat, ...] = ("srt",)
    output_dir: Path = field(default_factory=lambda: Path("./generated_subs"))
    transcribe: TranscribeOptions = field(default_factory=TranscribeOptions)
    style_name: str = "Default"
    font_size: int = 48
    glossary: tuple[GlossaryEntry, ...] = ()
    style_hint: str | None = None


@dataclass(slots=True)
class TranscribeResult:
    job_id: str
    video_path: Path | None
    audio_path: Path | None
    segments: list[Segment]
    info: TranscribeInfo
    outputs: dict[OutputFormat, Path]
    translation_meta: list[TranslationResult] = field(default_factory=list)


def run_pipeline(
    request: TranscribeRequest,
    *,
    job_id: str,
    backend: WhisperBackend | None = None,
    translator: GeminiTranslator | None = None,
    reporter: ProgressReporter | None = None,
    work_dir: Path | None = None,
) -> TranscribeResult:
    """Execute the pipeline synchronously.

    The caller is expected to wrap this in ``run_in_executor`` from the FastAPI
    handler — the heavy lifting (mlx-whisper, ffmpeg) is GIL-bound or
    subprocess.
    """
    backend = backend or select_backend()
    reporter = reporter or CollectingReporter()
    work_dir = work_dir or Path(tempfile.mkdtemp(prefix=f"sub_{job_id}_"))
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Download or open local
    emit(reporter, stage="download", pct=0, msg="Resolving source")
    if media_service.is_valid_url(request.source):
        emit(reporter, stage="download", pct=5, msg="Downloading")
        video_path = media_service.download_video(
            request.source,
            output_dir=work_dir,
            prefix=f"{job_id}_",
            on_progress=lambda pct, m: emit(reporter, stage="download", pct=pct, msg=m),
        )
        emit(reporter, stage="download", pct=100, msg=f"Saved {video_path.name}")
    else:
        path = Path(request.source)
        if not path.exists():
            raise FileNotFoundError(f"Source is neither URL nor existing file: {request.source}")
        video_path = path
        emit(reporter, stage="download", pct=100, msg=f"Using local {path.name}")

    # 2. WAV conversion
    if video_path.suffix.lower() == ".wav":
        audio_path = video_path
        emit(reporter, stage="convert", pct=100, msg="Input is WAV; skipping conversion")
    else:
        emit(reporter, stage="convert", pct=10, msg="Converting to 16 kHz mono WAV")
        audio_path = media_service.convert_to_wav(
            video_path,
            work_dir / f"{job_id}.wav",
        )
        emit(reporter, stage="convert", pct=100, msg=f"WAV ready: {audio_path.name}")

    # 3. Transcribe
    emit(
        reporter,
        stage="transcribe",
        pct=0,
        msg=f"Transcribing with {backend.name} ({request.transcribe.model})",
    )
    segments, info = backend.transcribe(audio_path, request.transcribe)
    emit(
        reporter,
        stage="transcribe",
        pct=100,
        msg=f"Done. lang={info.language} ({info.language_probability:.2f})",
    )

    # 4. Translate (optional)
    translation_meta: list[TranslationResult] = []
    if request.target_lang and request.target_lang != info.language:
        if translator is None:
            raise RuntimeError(
                "target_lang requested but no translator was supplied"
            )
        emit(
            reporter,
            stage="translate",
            pct=0,
            msg=f"{info.language} → {request.target_lang}",
        )
        # Backend Segment uses slots and is mutable on `text`, so we can update in place.
        translation_meta = translate_in_place(
            segments,
            translator,
            source_lang=info.language,
            target_lang=request.target_lang,
            glossary=list(request.glossary) or None,
            style_hint=request.style_hint,
        )
        emit(reporter, stage="translate", pct=100, msg="Translation complete")
    else:
        emit(reporter, stage="translate", pct=100, msg="Skipped (same language)")

    # 5. Write output(s)
    request.output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[OutputFormat, Path] = {}
    width = height = 0
    if video_path.exists():
        width, height = media_service.get_video_resolution(video_path)
    width = width or 1920
    height = height or 1080
    styles = style_service.load_styles()

    fmts = request.formats or ("srt",)
    base = request.output_dir / job_id
    for i, fmt in enumerate(fmts, start=1):
        emit(
            reporter,
            stage="write",
            pct=int((i - 1) / len(fmts) * 100),
            msg=f"Writing {fmt.upper()}",
        )
        if fmt == "srt":
            outputs[fmt] = subtitle_service.write_srt(segments, base.with_suffix(".srt"))
        elif fmt == "ass":
            outputs[fmt] = subtitle_service.write_ass(
                segments,
                base.with_suffix(".ass"),
                width=width,
                height=height,
                styles_data=styles,
                style_name=request.style_name,
                font_size=request.font_size,
            )
        elif fmt == "fcpxml":
            meta = media_service.get_video_metadata(video_path) if video_path.exists() else {}
            outputs[fmt] = subtitle_service.write_fcpxml(
                segments,
                base.with_suffix(".fcpxml"),
                width=width,
                height=height,
                frame_rate=float(meta.get("frame_rate") or 24.0) or 24.0,
                duration_sec=float(meta.get("duration") or 0.0) or None,
                font_size=request.font_size,
            )
        else:  # pragma: no cover - guarded by Literal
            raise ValueError(f"Unsupported format: {fmt}")
    emit(reporter, stage="write", pct=100, msg="All formats written")

    return TranscribeResult(
        job_id=job_id,
        video_path=video_path,
        audio_path=audio_path,
        segments=segments,
        info=info,
        outputs=outputs,
        translation_meta=translation_meta,
    )


__all__: Sequence[str] = (
    "OutputFormat",
    "TranscribeRequest",
    "TranscribeResult",
    "run_pipeline",
)
