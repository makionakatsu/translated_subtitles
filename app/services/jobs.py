from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.models import JobState, utc_now_iso


class JobCanceled(RuntimeError):
    pass


class JobContext:
    def __init__(self, manager: "JobManager", job_id: str) -> None:
        self.manager = manager
        self.job_id = job_id

    def check_cancel(self) -> None:
        if self.manager.jobs[self.job_id].cancel_requested:
            raise JobCanceled("Job canceled")

    async def update(
        self,
        progress: float,
        message: str,
        *,
        stage: Optional[str] = None,
        stage_label: Optional[str] = None,
        stage_progress: Optional[float] = None,
        current_item: Optional[int] = None,
        total_items: Optional[int] = None,
        eta_sec: Optional[float] = None,
        warnings: Optional[List[str]] = None,
    ) -> None:
        await self.manager.update(
            self.job_id,
            progress=progress,
            message=message,
            stage=stage,
            stage_label=stage_label,
            stage_progress=stage_progress,
            current_item=current_item,
            total_items=total_items,
            eta_sec=eta_sec,
            warnings=warnings,
        )


JobCallable = Callable[[JobContext], Awaitable[Dict[str, Any]]]


class JobManager:
    def __init__(self) -> None:
        self.jobs: Dict[str, JobState] = {}
        self.queue: "asyncio.Queue[tuple[str, JobCallable]]" = asyncio.Queue()
        self.subscribers: Dict[str, List[asyncio.Queue]] = {}
        self.worker_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if not self.worker_task or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())

    async def submit(self, kind: str, project_id: Optional[str], func: JobCallable) -> JobState:
        job_id = uuid.uuid4().hex[:12]
        state = JobState(id=job_id, kind=kind, project_id=project_id)
        self.jobs[job_id] = state
        await self.queue.put((job_id, func))
        await self._publish(job_id)
        return state

    async def cancel(self, job_id: str) -> JobState:
        state = self.jobs[job_id]
        state.cancel_requested = True
        if state.status == "queued":
            state.status = "canceled"
            state.finished_at = utc_now_iso()
        await self._publish(job_id)
        return state

    async def update(
        self,
        job_id: str,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        stage: Optional[str] = None,
        stage_label: Optional[str] = None,
        stage_progress: Optional[float] = None,
        current_item: Optional[int] = None,
        total_items: Optional[int] = None,
        eta_sec: Optional[float] = None,
        warnings: Optional[List[str]] = None,
    ) -> None:
        state = self.jobs[job_id]
        if progress is not None:
            state.progress = max(0.0, min(100.0, float(progress)))
        if message is not None:
            state.message = message
        if stage is not None:
            state.stage = stage
        if stage_label is not None:
            state.stage_label = stage_label
        if stage_progress is not None:
            state.stage_progress = max(0.0, min(100.0, float(stage_progress)))
        if current_item is not None:
            state.current_item = current_item
        if total_items is not None:
            state.total_items = total_items
        if eta_sec is not None:
            state.eta_sec = max(0.0, float(eta_sec))
        if warnings is not None:
            state.warnings = warnings
        await self._publish(job_id)

    async def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.setdefault(job_id, []).append(queue)
        await queue.put(self.jobs[job_id].model_dump())
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        subscribers = self.subscribers.get(job_id, [])
        if queue in subscribers:
            subscribers.remove(queue)

    async def _publish(self, job_id: str) -> None:
        state = self.jobs[job_id]
        payload = state.model_dump()
        for queue in self.subscribers.get(job_id, []):
            await queue.put(payload)

    async def _worker(self) -> None:
        while True:
            job_id, func = await self.queue.get()
            state = self.jobs[job_id]
            if state.status == "canceled":
                self.queue.task_done()
                continue
            started = time.monotonic()
            state.status = "running"
            state.stage = "running"
            state.stage_label = "実行中"
            state.started_at = utc_now_iso()
            await self._publish(job_id)
            try:
                context = JobContext(self, job_id)
                context.check_cancel()
                result = await func(context)
                context.check_cancel()
                state.status = "succeeded"
                state.progress = 100
                state.message = "completed"
                state.stage = "done"
                state.stage_label = "完了"
                state.stage_progress = 100
                state.result = result
            except JobCanceled as exc:
                state.status = "canceled"
                state.error = str(exc)
                state.message = "canceled"
                state.stage = "canceled"
                state.stage_label = "キャンセル"
            except Exception as exc:
                state.status = "failed"
                state.error = str(exc)
                state.message = "failed"
                state.stage = "failed"
                state.stage_label = "失敗"
            finally:
                state.finished_at = utc_now_iso()
                state.duration_sec = time.monotonic() - started
                await self._publish(job_id)
                self.queue.task_done()


job_manager = JobManager()
