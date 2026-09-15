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
    base_history_revision: int = 0
    error: str | None = None


class ChatRunInProgress(RuntimeError):
    def __init__(self, run_id: str):
        super().__init__("a chat run is already active")
        self.run_id = run_id


class ChatRunManager:
    """Own chat generation tasks so HTTP disconnects cannot cancel them."""

    def __init__(
        self,
        *,
        store: Any | None = None,
        completed_retention: int = 20,
        checkpoint_interval_seconds: float = 0.25,
        checkpoint_chars: int = 256,
    ):
        self._runs: dict[str, ChatRun] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._store = store
        self._completed_retention = completed_retention
        self._checkpoint_interval_seconds = checkpoint_interval_seconds
        self._checkpoint_chars = checkpoint_chars
        self._checkpoint_progress: dict[str, tuple[float, int]] = {}
        self._suspending: set[str] = set()
        if store is not None:
            for checkpoint in store.load_run_checkpoints():
                run = ChatRun(**checkpoint)
                self._runs[run.id] = run
            self._prune()

    def start(self, user_message: str, agent_loop: Any) -> ChatRun:
        active = self.active()
        if active is not None:
            raise ChatRunInProgress(active.id)
        run = ChatRun(
            id=f"chat_{uuid.uuid4().hex}",
            response_id=f"reply_{uuid.uuid4().hex}",
            user_message=user_message,
            base_history_revision=self._history_revision(),
        )
        self._runs[run.id] = run
        # The accepted input must be durable before the background task starts.
        # Otherwise a process exit between the HTTP 202 and task scheduling can
        # lose a message the UI already considers submitted.
        self._save_checkpoint(run, required=True)
        self._spawn(run, agent_loop)
        self._prune()
        log.info("后台对话任务已创建, run_id=%s", run.id)
        return run

    def resume(self, agent_loop: Any) -> None:
        """Resume durable unfinished runs once an event loop is available."""
        unfinished = [
            run
            for run in self._runs.values()
            if run.status in {"pending", "running"}
        ]
        if not unfinished:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            log.info("检测到待恢复对话，但当前没有运行中的事件循环")
            return

        for run in unfinished:
            task = self._tasks.get(run.id)
            if task is not None and not task.done():
                continue
            if self._was_history_committed(run):
                self._reconcile_completed(run, agent_loop)
                continue
            run.status = "pending"
            run.error = None
            run.revision += 1
            self._save_checkpoint(run)
            self._spawn(run, agent_loop, restart=True)
            log.info("未完成对话已从 SQLite 恢复, run_id=%s", run.id)

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
            self._save_checkpoint(run)
        return run

    async def shutdown(self) -> None:
        active = [
            (run_id, task)
            for run_id, task in self._tasks.items()
            if not task.done()
        ]
        self._suspending.update(run_id for run_id, _ in active)
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
                run.status = "pending"
                run.revision += 1
                self._save_checkpoint(run)
        self._suspending.difference_update(run_id for run_id, _ in active)

    def _spawn(self, run: ChatRun, agent_loop: Any, *, restart: bool = False) -> None:
        self._tasks[run.id] = asyncio.create_task(
            self._execute(run, agent_loop, restart=restart)
        )

    async def _execute(
        self,
        run: ChatRun,
        agent_loop: Any,
        *,
        restart: bool = False,
    ) -> None:
        started = time.monotonic()
        if restart:
            # Provider streams cannot be reattached after process exit. Start
            # the visible reply again instead of concatenating new output onto
            # the stale checkpoint.
            run.response_text = ""
            run.instruct_text = ""
            run.retrieved_memories = []
            run.safety_state = "normal"
            run.first_response_ms = None
            run.total_response_ms = 0
        run.status = "running"
        run.revision += 1
        self._save_checkpoint(run)
        received_done = False
        try:
            async for event in agent_loop.stream_once(
                run.user_message,
                run_id=run.id,
            ):
                event_type = event.get("type")
                if event_type == "delta":
                    first_delta = run.first_response_ms is None
                    if first_delta:
                        run.first_response_ms = self._elapsed_ms(started)
                    run.response_text += str(event.get("content", ""))
                    run.revision += 1
                    self._save_checkpoint(run, force=first_delta)
                elif event_type == "reset":
                    run.response_text = ""
                    run.revision += 1
                    self._save_checkpoint(run, force=True)
                elif event_type == "done":
                    ctx = event["context"]
                    run.response_text = ctx.response
                    run.instruct_text = ctx.instruct_text
                    run.retrieved_memories = list(ctx.retrieved_memories)
                    run.safety_state = ctx.safety_state
                    run.total_response_ms = self._elapsed_ms(started)
                    run.revision += 1
                    received_done = True
                    self._save_checkpoint(run, force=True)
            if not received_done:
                raise RuntimeError("对话流未返回完成事件")
            run.status = "completed"
            run.revision += 1
            self._save_checkpoint(run, force=True)
            self._prune()
            log.info(
                "后台对话任务完成, run_id=%s, total_ms=%d",
                run.id,
                run.total_response_ms,
            )
        except asyncio.CancelledError:
            run.status = "pending" if run.id in self._suspending else "cancelled"
            run.total_response_ms = self._elapsed_ms(started)
            run.revision += 1
            self._save_checkpoint(run, force=True)
            if run.status == "pending":
                log.info("后台对话任务已暂停并保存, run_id=%s", run.id)
            else:
                log.info("后台对话任务已取消, run_id=%s", run.id)
            raise
        except Exception as exc:
            run.status = "failed"
            run.total_response_ms = self._elapsed_ms(started)
            run.error = f"{type(exc).__name__}: 对话生成失败"
            run.revision += 1
            self._save_checkpoint(run, force=True)
            self._prune()
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
        removed = finished[:-self._completed_retention]
        for run_id in removed:
            self._runs.pop(run_id, None)
            self._tasks.pop(run_id, None)
            self._checkpoint_progress.pop(run_id, None)
        if self._store is not None and removed:
            self._store.delete_run_checkpoints(removed)

    def _save_checkpoint(
        self,
        run: ChatRun,
        *,
        force: bool = False,
        required: bool = False,
    ) -> None:
        if self._store is None:
            return
        now = time.monotonic()
        previous_time, previous_chars = self._checkpoint_progress.get(
            run.id,
            (0.0, -1),
        )
        if (
            not force
            and previous_chars >= 0
            and now - previous_time < self._checkpoint_interval_seconds
            and abs(len(run.response_text) - previous_chars) < self._checkpoint_chars
        ):
            return
        try:
            self._store.save_run_checkpoint(self._checkpoint_payload(run))
        except Exception:
            log.exception("后台对话检查点保存失败, run_id=%s", run.id)
            if required:
                self._runs.pop(run.id, None)
                raise
            return
        self._checkpoint_progress[run.id] = (now, len(run.response_text))

    def _history_revision(self) -> int:
        if self._store is None:
            return 0
        return self._store.revision()

    def _was_history_committed(self, run: ChatRun) -> bool:
        return bool(
            self._store is not None
            and self._store.last_completed_run_id() == run.id
            and self._store.revision() > run.base_history_revision
        )

    def _reconcile_completed(self, run: ChatRun, agent_loop: Any) -> None:
        messages = list(getattr(agent_loop, "messages", []))
        for index in range(len(messages) - 2, -1, -1):
            user = messages[index]
            assistant = messages[index + 1]
            if (
                user.get("role") == "user"
                and user.get("content") == run.user_message
                and assistant.get("role") == "assistant"
            ):
                run.response_text = str(assistant.get("content", ""))
                break
        run.status = "completed"
        run.error = None
        run.revision += 1
        self._save_checkpoint(run, force=True)
        self._prune()
        log.info("已提交对话的任务状态已修复, run_id=%s", run.id)

    @staticmethod
    def _checkpoint_payload(run: ChatRun) -> dict:
        return {
            "id": run.id,
            "response_id": run.response_id,
            "user_message": run.user_message,
            "status": run.status,
            "response_text": run.response_text,
            "instruct_text": run.instruct_text,
            "retrieved_memories": list(run.retrieved_memories),
            "safety_state": run.safety_state,
            "first_response_ms": run.first_response_ms,
            "total_response_ms": run.total_response_ms,
            "revision": run.revision,
            "base_history_revision": run.base_history_revision,
            "error": run.error,
        }

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.monotonic() - started) * 1000)
