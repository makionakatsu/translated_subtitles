"""In-memory job store with an asyncio.Queue per job for progress fan-out.

Phase 1 keeps everything in-process; Phase 4 swaps the implementation for
SQLite + Redis pub/sub without changing the call sites.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..models.segment import JobProgress
from ..workers.progress import ProgressReporter

JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


@dataclass
class JobRecord:
    id: str
    status: JobStatus = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    error: str | None = None
    outputs: dict[str, Path] = field(default_factory=dict)
    last_progress: JobProgress | None = None

    # Async fan-out: every SSE/WS subscriber gets its own queue.
    _subscribers: list[asyncio.Queue[JobProgress | None]] = field(default_factory=list, repr=False)

    def subscribe(self) -> asyncio.Queue[JobProgress | None]:
        q: asyncio.Queue[JobProgress | None] = asyncio.Queue()
        if self.last_progress is not None:
            q.put_nowait(self.last_progress)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[JobProgress | None]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(q)

    def publish(self, progress: JobProgress) -> None:
        self.last_progress = progress
        self.updated_at = datetime.utcnow()
        for q in self._subscribers:
            q.put_nowait(progress)

    def close(self) -> None:
        """Signal end-of-stream to all subscribers."""
        for q in self._subscribers:
            q.put_nowait(None)


class JobReporter(ProgressReporter):
    """Adapter: ``ProgressReporter`` that publishes into a :class:`JobRecord`."""

    def __init__(self, record: JobRecord) -> None:
        self._record = record

    def report(self, progress: JobProgress) -> None:
        self._record.publish(progress)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._tasks: dict[str, asyncio.Task[object]] = {}

    def create(self) -> JobRecord:
        job = JobRecord(id=uuid.uuid4().hex[:16])
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        return list(self._jobs.values())

    def attach(self, job_id: str, task: asyncio.Task[object]) -> None:
        self._tasks[job_id] = task

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        record = self._jobs.get(job_id)
        if record is not None:
            record.status = "cancelled"
            record.close()
        return True


_store: JobStore | None = None


def get_store() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore()
    return _store


def reset_store() -> None:
    """Test helper."""
    global _store
    _store = None
