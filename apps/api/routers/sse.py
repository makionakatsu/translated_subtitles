"""Server-Sent Events: progress fan-out for jobs.

The Next.js editor opens ``EventSource('/sse/jobs/{id}')`` and consumes a
stream of :class:`apps.api.models.segment.JobProgress` payloads. The stream
ends when the job reaches a terminal state.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..store.jobs import JobStore, get_store

router = APIRouter(prefix="/sse", tags=["sse"])


@router.get("/jobs/{job_id}")
async def job_progress(
    job_id: str,
    store: JobStore = Depends(get_store),
) -> EventSourceResponse:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(404, "Unknown job id")

    async def stream() -> AsyncIterator[dict[str, str]]:
        queue = record.subscribe()
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield {"event": "end", "data": json.dumps({"status": record.status})}
                    return
                yield {
                    "event": "progress",
                    "data": event.model_dump_json(),
                }
        except asyncio.CancelledError:
            return
        finally:
            record.unsubscribe(queue)

    return EventSourceResponse(stream())
