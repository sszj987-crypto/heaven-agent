import asyncio
from types import SimpleNamespace

import pytest

from src.agent.conversation_store import ConversationStore
from src.services.chat_runs import ChatRunInProgress, ChatRunManager


class ControlledAgent:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream_once(self, message, *, run_id=None):
        self.started.set()
        yield {"type": "delta", "content": "正在"}
        await self.release.wait()
        yield {"type": "delta", "content": "回复"}
        yield {
            "type": "done",
            "context": SimpleNamespace(
                response="正在回复",
                instruct_text="自然地说",
                retrieved_memories=[],
                safety_state="normal",
            ),
        }


async def test_chat_run_continues_without_a_waiting_http_consumer():
    manager = ChatRunManager()
    agent = ControlledAgent()

    run = manager.start("你好", agent)
    await agent.started.wait()

    assert manager.active() is run
    assert run.status == "running"
    assert run.response_text == "正在"

    agent.release.set()
    await manager._tasks[run.id]

    assert run.status == "completed"
    assert run.response_text == "正在回复"
    assert run.instruct_text == "自然地说"
    assert manager.active() is None


async def test_chat_run_rejects_a_second_active_turn():
    manager = ChatRunManager()
    agent = ControlledAgent()
    first = manager.start("第一条", agent)
    await agent.started.wait()

    with pytest.raises(ChatRunInProgress) as exc_info:
        manager.start("第二条", agent)

    assert exc_info.value.run_id == first.id
    await manager.cancel(first.id)


async def test_chat_run_can_be_explicitly_cancelled():
    manager = ChatRunManager()
    agent = ControlledAgent()
    run = manager.start("停止", agent)
    await agent.started.wait()

    await manager.cancel(run.id)

    assert run.status == "cancelled"
    assert manager.active() is None


async def test_chat_run_can_be_cancelled_before_its_task_starts():
    manager = ChatRunManager()
    agent = ControlledAgent()
    run = manager.start("立即停止", agent)

    await manager.cancel(run.id)

    assert run.status == "cancelled"
    assert manager.active() is None


async def test_chat_run_failure_hides_provider_details():
    class FailingAgent:
        async def stream_once(self, _message, *, run_id=None):
            raise RuntimeError("private provider response")
            yield

    manager = ChatRunManager()
    run = manager.start("私密输入", FailingAgent())
    await manager._tasks[run.id]

    assert run.status == "failed"
    assert run.error == "RuntimeError: 对话生成失败"
    assert "provider" not in run.error


async def test_completed_chat_run_is_restored_from_sqlite(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    manager = ChatRunManager(store=store)
    agent = ControlledAgent()

    run = manager.start("你好", agent)
    await agent.started.wait()
    partial = ChatRunManager(store=store).get(run.id)
    assert partial.status == "running"
    assert partial.response_text == "正在"
    agent.release.set()
    await manager._tasks[run.id]

    restored = ChatRunManager(store=store).get(run.id)
    assert restored.status == "completed"
    assert restored.response_text == "正在回复"
    assert restored.instruct_text == "自然地说"


async def test_unfinished_chat_run_resumes_after_restart(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    store.save_run_checkpoint({
        "id": "chat_interrupted",
        "response_id": "reply_interrupted",
        "user_message": "继续回复",
        "status": "running",
        "response_text": "旧的部分回复",
        "instruct_text": "",
        "retrieved_memories": [],
        "safety_state": "normal",
        "first_response_ms": 20,
        "total_response_ms": 0,
        "revision": 2,
        "base_history_revision": 0,
        "error": None,
    })
    manager = ChatRunManager(store=store)
    agent = ControlledAgent()

    manager.resume(agent)
    await agent.started.wait()
    resumed = manager.get("chat_interrupted")
    assert resumed.status == "running"
    # Regeneration restarts the partial text instead of appending to a stale
    # provider stream that no longer exists.
    assert resumed.response_text == "正在"

    agent.release.set()
    await manager._tasks[resumed.id]
    assert resumed.status == "completed"
    assert resumed.response_text == "正在回复"


async def test_restart_reconciles_history_commit_without_generating_twice(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    store.save_run_checkpoint({
        "id": "chat_committed",
        "response_id": "reply_committed",
        "user_message": "不要重复",
        "status": "running",
        "response_text": "不要",
        "instruct_text": "",
        "retrieved_memories": [],
        "safety_state": "normal",
        "first_response_ms": 10,
        "total_response_ms": 0,
        "revision": 2,
        "base_history_revision": 0,
        "error": None,
    })
    store.replace(
        [
            {"role": "user", "content": "不要重复"},
            {"role": "assistant", "content": "只保留一次"},
        ],
        completed_run_id="chat_committed",
    )

    class MustNotRun:
        messages = store.load()

        async def stream_once(self, _message, *, run_id=None):
            raise AssertionError("committed turn must not be generated again")
            yield

    manager = ChatRunManager(store=store)
    manager.resume(MustNotRun())

    run = manager.get("chat_committed")
    assert run.status == "completed"
    assert run.response_text == "只保留一次"
    assert run.id not in manager._tasks


async def test_graceful_shutdown_keeps_active_run_resumable(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    manager = ChatRunManager(store=store)
    agent = ControlledAgent()
    run = manager.start("稍后继续", agent)
    await agent.started.wait()

    await manager.shutdown()

    assert run.status == "pending"
    restored = ChatRunManager(store=store).get(run.id)
    assert restored.status == "pending"
