"""Per-job style overrides + live ASS payload for the JASSUB preview.

The editor reads the current style with ``GET /api/jobs/{id}/style``, mutates
keys via ``PATCH``, and feeds ``GET /api/jobs/{id}/ass`` straight into the
JASSUB instance. Because libass renders deterministically, the on-screen
preview matches the future ffmpeg burn-in byte-for-byte.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..services.style_service import load_styles
from ..services.subtitle_service import (
    format_ass_time,
    render_ass_header,
)
from ..store.jobs import JobStore, get_store

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["style"])


class StyleOut(BaseModel):
    style_name: str
    font_size: int
    overrides: dict[str, str] = Field(default_factory=dict)
    available_styles: list[str] = Field(default_factory=list)


class StylePatch(BaseModel):
    style_name: str | None = None
    font_size: int | None = None
    overrides: dict[str, str] | None = None


@router.get("/style", response_model=StyleOut)
async def get_style(
    job_id: str,
    store: Annotated[JobStore, Depends(get_store)],
) -> StyleOut:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    styles = load_styles()
    return StyleOut(
        style_name=record.style_name,
        font_size=record.font_size,
        overrides=record.style_overrides,
        available_styles=list(styles.keys()),
    )


@router.patch("/style", response_model=StyleOut)
async def patch_style(
    job_id: str,
    payload: StylePatch,
    store: Annotated[JobStore, Depends(get_store)],
) -> StyleOut:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")
    if payload.style_name is not None:
        record.style_name = payload.style_name
    if payload.font_size is not None:
        record.font_size = max(8, min(400, int(payload.font_size)))
    if payload.overrides is not None:
        # Merge rather than replace so the editor can PATCH a single key.
        record.style_overrides = {**record.style_overrides, **payload.overrides}
    styles = load_styles()
    return StyleOut(
        style_name=record.style_name,
        font_size=record.font_size,
        overrides=record.style_overrides,
        available_styles=list(styles.keys()),
    )


@router.get("/ass", response_class=Response)
async def get_ass(
    job_id: str,
    store: Annotated[JobStore, Depends(get_store)],
) -> Response:
    """Return the live ASS document.

    Always returns the latest segments + the current style, so the editor can
    feed it into JASSUB whenever either changes.
    """
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")

    styles = load_styles()
    base = styles.get(record.style_name, next(iter(styles.values()), {}))
    merged_styles = {record.style_name: {**base, **record.style_overrides}}

    header = render_ass_header(
        width=record.width,
        height=record.height,
        styles_data=merged_styles,
        style_name=record.style_name,
        font_size=record.font_size,
    )

    lines = [header]
    for seg in record.segments:
        start = format_ass_time(seg.start)
        end = format_ass_time(seg.end)
        text = seg.text.strip().replace("\r\n", "\n").replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{start},{end},{record.style_name},,0,0,0,,{text}\n"
        )
    return Response("".join(lines), media_type="text/x-ass; charset=utf-8")
