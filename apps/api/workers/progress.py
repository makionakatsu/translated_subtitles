"""Progress reporter abstraction.

The transcribe pipeline reports progress through a small callable protocol so
the same worker can be driven by:

* an in-process queue (default `asyncio.Queue`-backed reporter for the API)
* arq (Redis pub/sub) when scaled out
* a no-op reporter in unit tests
"""
from __future__ import annotations

from typing import Protocol

from ..models.segment import JobProgress, Stage


class ProgressReporter(Protocol):
    def report(self, progress: JobProgress) -> None:  # pragma: no cover - protocol only
        ...


class NullReporter:
    """Discards updates; useful in unit tests."""

    def report(self, progress: JobProgress) -> None:
        return


class CollectingReporter:
    """Stores updates in memory; useful in tests and the in-process API."""

    def __init__(self) -> None:
        self.events: list[JobProgress] = []

    def report(self, progress: JobProgress) -> None:
        self.events.append(progress)


def emit(
    reporter: ProgressReporter,
    *,
    stage: Stage,
    pct: float,
    msg: str,
    eta_sec: float | None = None,
) -> None:
    reporter.report(JobProgress(stage=stage, pct=pct, msg=msg, eta_sec=eta_sec))
