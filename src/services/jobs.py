from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Coroutine


@dataclass
class Job:
    id: str
    kind: str
    status: str = "pending"
    result: Any = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(self, kind: str, work: Coroutine[Any, Any, Any]) -> Job:
        job = Job(id=f"job_{uuid.uuid4().hex[:12]}", kind=kind)
        self._jobs[job.id] = job
        self._tasks[job.id] = asyncio.create_task(self._run(job, work))
        return job

    async def _run(self, job: Job, work: Coroutine[Any, Any, Any]) -> None:
        job.status = "running"
        try:
            job.result = await work
            job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
            raise
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: 任务执行失败"

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown job: {job_id}") from exc

    def list_active(self) -> list[Job]:
        return [job for job in self._jobs.values() if job.status in {"pending", "running"}]

    async def wait(self, job_id: str) -> None:
        await self._tasks[job_id]

    async def shutdown(self) -> None:
        active = [task for task in self._tasks.values() if not task.done()]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
