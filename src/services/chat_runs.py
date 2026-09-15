"""Connection-independent background execution for chat turns."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from ..config.logger import get_logger


log = get_logger("chat_runs")
ChatRunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


@dataclass
class ChatRun:
    id: str
    response_id: str
    user_message: str
    status: ChatRunStatus = "pending"
    response_text: str = ""
    instruct_text: str = ""
    retrieved_memories: list[dict] = field(default_factory=list)
    safety_state: str = "normal"
    first_response_ms: int | None = None
    total_response_ms: int = 0
    revision: int = 0
    error: str | None = None


class ChatRunInProgress(RuntimeError):
    def __init__(self, run_id: str):
        super().__init__("a chat run is already active")
        self.run_id = run_id


class ChatRunManager:
    """Own chat generation tasks so HTTP disconnects cannot cancel them."""

    def __init__(self, *, completed_retention: int = 20):
        self._runs: dict[str, ChatRun] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._completed_retention = completed_retention

    def start(self, user_message: str, agent_loop: Any) -> ChatRun:
        active = self.active()
        if active is not None:
            raise ChatRunInProgress(active.id)
        run = ChatRun(
            id=f"chat_{uuid.uuid4().hex}",
            response_id=f"reply_{uuid.uuid4().hex}",
            user_message=user_message,
        )
        self._runs[run.id] = run
        self._tasks[run.id] = asyncio.create_task(self._execute(run, agent_loop))
        self._prune()
        log.info("后台对话任务已创建, run_id=%s", run.id)
        return run

    def get(self, run_id: str) -> ChatRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"unknown chat run: {run_id}") from exc

    def active(self) -> ChatRun | None:
        return next(
            (
                run
                for run in reversed(list(self._runs.values()))
                if run.status in {"pending", "running"}
            ),
            None,
        )

    async def cancel(self, run_id: str) -> ChatRun:
        run = self.get(run_id)
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if run.status in {"pending", "running"}:
            run.status = "cancelled"
            run.revision += 1
        return run

    async def shutdown(self) -> None:
        active = [
            (run_id, task)
            for run_id, task in self._tasks.items()
            if not task.done()
        ]
        for _, task in active:
            task.cancel()
        if active:
            await asyncio.gather(
                *(task for _, task in active),
                return_exceptions=True,
            )
        for run_id, _ in active:
            run = self._runs[run_id]
            if run.status in {"pending", "running"}:
                run.status = "cancelled"
                run.revision += 1

    async def _execute(self, run: ChatRun, agent_loop: Any) -> None:
        started = time.monotonic()
        run.status = "running"
        run.revision += 1
        received_done = False
        try:
            async for event in agent_loop.stream_once(run.user_message):
                event_type = event.get("type")
                if event_type == "delta":
                    if run.first_response_ms is None:
                        run.first_response_ms = self._elapsed_ms(started)
                    run.response_text += str(event.get("content", ""))
                    run.revision += 1
                elif event_type == "reset":
                    run.response_text = ""
                    run.revision += 1
                elif event_type == "done":
                    ctx = event["context"]
                    run.response_text = ctx.response
                    run.instruct_text = ctx.instruct_text
                    run.retrieved_memories = list(ctx.retrieved_memories)
                    run.safety_state = ctx.safety_state
                    run.total_response_ms = self._elapsed_ms(started)
                    run.revision += 1
                    received_done = True
            if not received_done:
                raise RuntimeError("对话流未返回完成事件")
            run.status = "completed"
            run.revision += 1
            log.info(
                "后台对话任务完成, run_id=%s, total_ms=%d",
                run.id,
                run.total_response_ms,
            )
        except asyncio.CancelledError:
            run.status = "cancelled"
            run.total_response_ms = self._elapsed_ms(started)
            run.revision += 1
            log.info("后台对话任务已取消, run_id=%s", run.id)
            raise
        except Exception as exc:
            run.status = "failed"
            run.total_response_ms = self._elapsed_ms(started)
            run.error = f"{type(exc).__name__}: 对话生成失败"
            run.revision += 1
            log.error(
                "后台对话任务失败, run_id=%s, error_type=%s",
                run.id,
                type(exc).__name__,
            )

    def _prune(self) -> None:
        finished = [
            run_id
            for run_id, run in self._runs.items()
            if run.status in {"completed", "failed", "cancelled"}
        ]
        for run_id in finished[:-self._completed_retention]:
            self._runs.pop(run_id, None)
            self._tasks.pop(run_id, None)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.monotonic() - started) * 1000)
