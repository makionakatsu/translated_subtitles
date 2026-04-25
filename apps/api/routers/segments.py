"""Segment editor endpoints.

The editor UI loads a job's segments via ``GET /api/jobs/{id}/segments`` after
the pipeline finishes, then PATCHes individual edits as the user types.
``POST .../segments/{idx}/retranslate`` returns alternate AI candidates.
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..models.segment import Segment
from ..services.style_service import load_styles
from ..services.subtitle_service import (
    write_ass,
    write_fcpxml,
    write_srt,
)
from ..services.translate_service import GeminiTranslator
from ..store.jobs import JobStore, get_store

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["segments"])


class SegmentEdit(BaseModel):
    """Patch payload for a single segment.

    All fields are optional — the client only needs to send what changed. The
    server applies the patch atomically per segment.
    """

    start: float | None = None
    end: float | None = None
    text: str | None = None
    speaker: str | None = None
    locked: bool | None = None


class SegmentBulkPatch(BaseModel):
    edits: dict[int, SegmentEdit]


class SegmentsOut(BaseModel):
    job_id: str
    source_language: str | None
    target_language: str | None
    width: int
    height: int
    segments: list[Segment]


class RetranslateIn(BaseModel):
    candidates: int = Field(default=3, ge=1, le=8)


class RetranslateOut(BaseModel):
    candidates: list[str]


@router.get("/segments", response_model=SegmentsOut)
async def get_segments(
    job_id: str,
    store: Annotated[JobStore, Depends(get_store)],
) -> SegmentsOut:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    return SegmentsOut(
        job_id=job_id,
        source_language=record.source_language,
        target_language=record.target_language,
        width=record.width,
        height=record.height,
        segments=record.segments,
    )


@router.patch("/segments", response_model=SegmentsOut)
async def patch_segments(
    job_id: str,
    payload: SegmentBulkPatch,
    store: Annotated[JobStore, Depends(get_store)],
) -> SegmentsOut:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    by_id = {seg.id: seg for seg in record.segments}
    for sid, edit in payload.edits.items():
        seg = by_id.get(sid)
        if seg is None:
            continue
        data = seg.model_dump()
        for k, v in edit.model_dump(exclude_unset=True).items():
            data[k] = v
        # Touch updated_at so the optimistic-lock check in Phase 4 can compare.
        from datetime import datetime as _dt

        data["updated_at"] = _dt.utcnow()
        by_id[sid] = Segment(**data)
    record.segments = sorted(by_id.values(), key=lambda s: s.start)
    return SegmentsOut(
        job_id=job_id,
        source_language=record.source_language,
        target_language=record.target_language,
        width=record.width,
        height=record.height,
        segments=record.segments,
    )


@router.post("/segments/{idx}/retranslate", response_model=RetranslateOut)
async def retranslate_segment(
    job_id: str,
    idx: int,
    payload: RetranslateIn,
    store: Annotated[JobStore, Depends(get_store)],
) -> RetranslateOut:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    seg = next((s for s in record.segments if s.id == idx), None)
    if seg is None:
        raise HTTPException(404, f"Segment {idx} not found")
    if record.source_language is None or record.target_language is None:
        raise HTTPException(400, "Job has no language pair (was translation enabled?)")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(400, "GEMINI_API_KEY env var must be set")
    translator = GeminiTranslator(api_key=api_key)
    candidates = translator.retranslate_one(
        seg.original_text or seg.text,
        source_lang=record.source_language,
        target_lang=record.target_language,
        candidates=payload.candidates,
    )
    return RetranslateOut(candidates=candidates)


@router.post("/regenerate")
async def regenerate_outputs(
    job_id: str,
    store: Annotated[JobStore, Depends(get_store)],
) -> dict[str, str]:
    """Re-write the SRT/ASS/FCPXML files using the *current* edited segments.

    Useful after a round of edits so ``/api/jobs/{id}/outputs/{fmt}`` returns
    the user's latest edits without re-running the entire pipeline.
    """
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    if not record.segments:
        raise HTTPException(400, "No segments to write")

    fresh: dict[str, str] = {}
    styles = load_styles()
    base = styles.get(record.style_name, next(iter(styles.values()), {}))
    merged_styles = {record.style_name: {**base, **record.style_overrides}}

    for fmt, path in record.outputs.items():
        from pathlib import Path

        out_path = Path(path)
        if fmt == "srt":
            write_srt(record.segments, out_path)
        elif fmt == "ass":
            write_ass(
                record.segments,
                out_path,
                width=record.width,
                height=record.height,
                styles_data=merged_styles,
                style_name=record.style_name,
                font_size=record.font_size,
            )
        elif fmt == "fcpxml":
            write_fcpxml(
                record.segments,
                out_path,
                width=record.width,
                height=record.height,
                font_size=record.font_size,
            )
        fresh[fmt] = str(out_path)
    return fresh
