"""Jobs router: create jobs, query status, list outputs."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..backends.base import TranscribeOptions, select_backend
from ..models.segment import Segment as SegmentOut
from ..services.media_service import get_video_resolution
from ..services.transcribe_service import (
    OutputFormat,
    TranscribeRequest,
    TranscribeResult,
    run_pipeline,
)
from ..services.translate_service import GeminiTranslator, GlossaryEntry
from ..store.jobs import JobReporter, JobStore, get_store

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


# ── Request / response models ───────────────────────────────────────────────


class GlossaryEntryIn(BaseModel):
    source: str
    target: str
    note: str | None = None


class TranscribeJobIn(BaseModel):
    source: str = Field(..., description="A URL (yt-dlp) or absolute path to a local file")
    target_lang: str | None = Field(None, description="Two-letter target. None to skip translation")
    formats: list[OutputFormat] = Field(default_factory=lambda: ["srt"])
    output_dir: str = "./generated_subs"
    style_name: str = "Default"
    font_size: int = 48
    style_hint: str | None = None
    glossary: list[GlossaryEntryIn] = Field(default_factory=list)

    # Backend / model
    backend: Literal["mlx", "faster_whisper", "auto"] = "auto"
    model: str = "large-v3-turbo"
    language: str | None = None
    initial_prompt: str | None = None
    vad_filter: bool = True


class JobStatusOut(BaseModel):
    id: str
    status: str
    error: str | None = None
    last_stage: str | None = None
    last_pct: float | None = None
    last_msg: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("", status_code=202, response_model=JobStatusOut)
async def create_job(
    payload: TranscribeJobIn,
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_store),
) -> JobStatusOut:
    """Kick off a transcription/translation job in the background."""
    record = store.create()

    options = TranscribeOptions(
        model=payload.model,
        language=payload.language,
        initial_prompt=payload.initial_prompt,
        vad_filter=payload.vad_filter,
    )
    backend = select_backend(payload.backend)
    translator: GeminiTranslator | None = None
    if payload.target_lang:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="GEMINI_API_KEY env var must be set when target_lang is provided",
            )
        translator = GeminiTranslator(api_key=api_key)

    request = TranscribeRequest(
        source=payload.source,
        target_lang=payload.target_lang,
        formats=tuple(payload.formats),
        output_dir=Path(payload.output_dir),
        transcribe=options,
        style_name=payload.style_name,
        font_size=payload.font_size,
        glossary=tuple(GlossaryEntry(**g.model_dump()) for g in payload.glossary),
        style_hint=payload.style_hint,
    )

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        record.status = "running"
        try:
            result: TranscribeResult = await loop.run_in_executor(
                None,
                lambda: run_pipeline(
                    request,
                    job_id=record.id,
                    backend=backend,
                    translator=translator,
                    reporter=JobReporter(record),
                ),
            )
            record.status = "completed"
            record.outputs = {fmt: path for fmt, path in result.outputs.items()}
            record.source_language = result.info.language
            record.target_language = payload.target_lang
            record.video_path = str(result.video_path) if result.video_path else None
            if result.video_path is not None:
                w, h = get_video_resolution(result.video_path)
                record.width = w or 1920
                record.height = h or 1080
            # Snapshot the AI segments into editor-facing pydantic models.
            editor_segments = [
                SegmentOut(
                    id=i,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    original_text=seg.text,
                    speaker=seg.speaker,
                    avg_logprob=seg.avg_logprob,
                )
                for i, seg in enumerate(result.segments)
            ]
            record.segments = editor_segments
            record.original_segments = list(editor_segments)
        except asyncio.CancelledError:
            record.status = "cancelled"
            raise
        except Exception as e:
            logger.exception("Job %s failed", record.id)
            record.status = "failed"
            record.error = str(e)
        finally:
            record.close()

    task = asyncio.create_task(_run())
    store.attach(record.id, task)

    return _to_status_out(record)


@router.get("", response_model=list[JobStatusOut])
async def list_jobs(store: JobStore = Depends(get_store)) -> list[JobStatusOut]:
    return [_to_status_out(r) for r in store.list()]


@router.get("/{job_id}", response_model=JobStatusOut)
async def get_job(job_id: str, store: JobStore = Depends(get_store)) -> JobStatusOut:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    return _to_status_out(record)


@router.post("/{job_id}/cancel", response_model=JobStatusOut)
async def cancel_job(job_id: str, store: JobStore = Depends(get_store)) -> JobStatusOut:
    if not store.cancel(job_id):
        raise HTTPException(404, "Unknown or completed job")
    record = store.get(job_id)
    assert record is not None
    return _to_status_out(record)


@router.get("/{job_id}/outputs/{fmt}")
async def download_output(
    job_id: str,
    fmt: str,
    store: JobStore = Depends(get_store),
) -> FileResponse:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    path = record.outputs.get(fmt)
    if path is None or not Path(path).exists():
        raise HTTPException(404, f"Output {fmt} not available")
    return FileResponse(path, filename=Path(path).name)


@router.get("/{job_id}/media")
async def stream_media(
    job_id: str,
    store: JobStore = Depends(get_store),
) -> FileResponse:
    """Stream the source video so the editor's <video> can play it."""
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    if not record.video_path or not Path(record.video_path).exists():
        raise HTTPException(404, "Source media not available")
    return FileResponse(record.video_path, filename=Path(record.video_path).name)


# ── helpers ─────────────────────────────────────────────────────────────────


def _to_status_out(record) -> JobStatusOut:  # type: ignore[no-untyped-def]
    last = record.last_progress
    return JobStatusOut(
        id=record.id,
        status=record.status,
        error=record.error,
        last_stage=last.stage if last else None,
        last_pct=last.pct if last else None,
        last_msg=last.msg if last else None,
        outputs={fmt: str(path) for fmt, path in record.outputs.items()},
    )
