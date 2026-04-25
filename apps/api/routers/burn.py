"""Burn-in router: render the ASS / SRT into a hard-subbed mp4.

The endpoint kicks ffmpeg off as a FastAPI BackgroundTask so the response
returns 202 immediately. ffmpeg progress is forwarded to the SSE stream
(stage="burn") and the resulting mp4 lands at
``/api/jobs/{id}/outputs/burned``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from ..models.segment import JobProgress
from ..services import burn_service, media_service, style_service
from ..services.subtitle_service import write_ass
from ..store.jobs import JobRecord, JobReporter, JobStore, get_store

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["burn"])
logger = logging.getLogger(__name__)


class BurnIn(BaseModel):
    # The user can pick any subtitle file the job has already produced.
    # When omitted we render the live ASS (matches the editor preview).
    source_format: str | None = None


def _do_burn(record: JobRecord, sub_path: Path, duration: float) -> None:
    reporter = JobReporter(record)

    def _on_progress(pct: float, msg: str) -> None:
        reporter.report(JobProgress(stage="burn", pct=pct, msg=msg))

    out_dir = Path(record.video_path or ".").parent
    try:
        output_path = burn_service.burn_subtitles(
            Path(record.video_path or ""),
            sub_path,
            out_dir=out_dir,
            font_size=record.font_size,
            on_progress=_on_progress,
            duration_sec=duration,
        )
        record.outputs["burned"] = output_path
        reporter.report(JobProgress(stage="burn", pct=100.0, msg="Burn complete"))
    except Exception as e:
        logger.exception("Burn failed for %s", record.id)
        record.error = str(e)
        reporter.report(JobProgress(stage="burn", pct=0.0, msg=f"Failed: {e}"))


@router.post("/burn", status_code=202)
async def burn_in(
    job_id: str,
    payload: BurnIn,
    background_tasks: BackgroundTasks,
    store: Annotated[JobStore, Depends(get_store)],
) -> dict[str, str]:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    if not record.video_path or not Path(record.video_path).exists():
        raise HTTPException(400, "Source video not available")

    sub_path: Path
    if payload.source_format:
        candidate = record.outputs.get(payload.source_format)
        if candidate is None or not Path(candidate).exists():
            raise HTTPException(404, f"Output {payload.source_format} not available")
        sub_path = Path(candidate)
    else:
        # Render the live ASS to a temp file matching the editor preview.
        styles = style_service.load_styles()
        base = styles.get(record.style_name, next(iter(styles.values()), {}))
        merged_styles = {record.style_name: {**base, **record.style_overrides}}
        live_path = Path(record.video_path).with_suffix(".live.ass")
        write_ass(
            record.segments,
            live_path,
            width=record.width,
            height=record.height,
            styles_data=merged_styles,
            style_name=record.style_name,
            font_size=record.font_size,
        )
        sub_path = live_path

    duration = float(media_service.get_video_metadata(record.video_path).get("duration") or 0.0)
    background_tasks.add_task(_do_burn, record, sub_path, duration)
    return {"status": "accepted"}
