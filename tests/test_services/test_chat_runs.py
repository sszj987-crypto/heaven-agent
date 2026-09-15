import asyncio
from types import SimpleNamespace

import pytest

from src.services.chat_runs import ChatRunInProgress, ChatRunManager


class ControlledAgent:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream_once(self, message):
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
        async def stream_once(self, _message):
            raise RuntimeError("private provider response")
            yield

    manager = ChatRunManager()
    run = manager.start("私密输入", FailingAgent())
    await manager._tasks[run.id]

    assert run.status == "failed"
    assert run.error == "RuntimeError: 对话生成失败"
    assert "provider" not in run.error
