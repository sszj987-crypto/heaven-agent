import asyncio
from types import SimpleNamespace

from src.agent.context import PipelineContext
from src.agent.conversation_store import ConversationStore
from src.agent.loop import AgentLoop
from src.services.safety import SafetyPolicy
from src.agent.modules.postllm.quality_check import QualityCheckModule


class FakePipeline:
    async def run_prellm(self, ctx):
        ctx.llm_messages = [{"role": "user", "content": ctx.user_message}]
        return ctx

    async def run_postllm(self, ctx):
        return ctx

    async def run_postoutput(self, ctx):
        return ctx


class MeasuringLLM:
    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def stream(self, messages):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        yield '{"reply":"收到"}'
        self.active -= 1


async def test_run_once_serializes_concurrent_turns_for_one_soul():
    llm = MeasuringLLM()
    loop = AgentLoop(
        llm=llm,
        pipeline=FakePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
    )

    first, second = await asyncio.gather(loop.run_once("第一条"), loop.run_once("第二条"))

    assert llm.max_active == 1
    assert first.response == "收到"
    assert second.response == "收到"
    assert [message["content"] for message in loop.messages] == ["第一条", "收到", "第二条", "收到"]


async def test_completed_turn_is_restored_from_sqlite_after_restart(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    first = AgentLoop(
        llm=MeasuringLLM(),
        pipeline=FakePipeline(),
        history_store=store,
        max_conversation_turns=20,
        max_regenerate=0,
    )

    await first.run_once("第一条")
    restored = AgentLoop(
        llm=MeasuringLLM(),
        pipeline=FakePipeline(),
        history_store=ConversationStore(store.path),
        max_conversation_turns=20,
        max_regenerate=0,
    )

    assert [message["content"] for message in restored.messages] == ["第一条", "收到"]


async def test_background_run_id_is_committed_with_its_history(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    loop = AgentLoop(
        llm=MeasuringLLM(),
        pipeline=FakePipeline(),
        history_store=store,
        max_conversation_turns=20,
        max_regenerate=0,
    )

    events = [
        event
        async for event in loop.stream_once("需要原子提交", run_id="chat_atomic")
    ]

    assert events[-1]["type"] == "done"
    assert store.last_completed_run_id() == "chat_atomic"
    assert store.revision() == 1


async def test_persistence_failure_rolls_back_in_memory_turn():
    class FailingStore:
        def load(self):
            return []

        def replace(self, _messages):
            raise OSError("disk unavailable")

    loop = AgentLoop(
        llm=MeasuringLLM(),
        pipeline=FakePipeline(),
        history_store=FailingStore(),
        max_conversation_turns=20,
        max_regenerate=0,
    )

    import pytest
    with pytest.raises(OSError, match="disk unavailable"):
        await loop.run_once("不应留在内存")

    assert loop.messages == []


async def test_stream_once_emits_reply_deltas_before_the_completed_context():
    class ChunkedLLM:
        async def stream(self, _messages):
            for chunk in ('{"reply":"你', '好\\n\\u5440",', '"instruct":"温柔地说"}'):
                yield chunk

    loop = AgentLoop(
        llm=ChunkedLLM(),
        pipeline=FakePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
    )

    events = [event async for event in loop.stream_once("你好")]

    assert "".join(event["content"] for event in events if event["type"] == "delta") == "你好\n呀"
    assert events[-1]["type"] == "done"
    assert events[-1]["context"].response == "你好\n呀"
    assert events[-1]["context"].instruct_text == "温柔地说"


def test_update_llm_client_changes_subsequent_client():
    first = MeasuringLLM()
    second = MeasuringLLM()
    loop = AgentLoop(
        llm=first,
        pipeline=FakePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
    )

    loop.update_llm_client(second)

    assert loop._llm is second


async def test_crisis_turn_bypasses_roleplay_model():
    class GuardLLM:
        async def stream(self, _messages):
            raise AssertionError("roleplay model must not run in crisis mode")
            yield ""

    loop = AgentLoop(
        llm=GuardLLM(),
        pipeline=FakePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
        safety_policy=SafetyPolicy(),
    )

    result = await loop.run_once("我不想活了")

    assert result.safety_state == "crisis"
    assert "现实中" in result.response


async def test_unprompted_afterlife_reply_fails_closed_after_regeneration_limit():
    class AlwaysAfterlifeLLM:
        def __init__(self):
            self.calls = 0

        async def stream(self, _messages):
            self.calls += 1
            yield '{"reply":"我没事，在这边挺好的！","instruct":"轻快地说"}'

    class NarrativePipeline(FakePipeline):
        def __init__(self):
            self.quality = QualityCheckModule()

        async def run_postllm(self, ctx):
            return await self.quality.process(ctx)

    llm = AlwaysAfterlifeLLM()
    loop = AgentLoop(
        llm=llm,
        pipeline=NarrativePipeline(),
        max_conversation_turns=20,
        max_regenerate=1,
    )

    events = [event async for event in loop.stream_once("你好")]
    context = events[-1]["context"]

    assert llm.calls == 2
    assert context.response == "看到你的消息啦。最近怎么样？"
    assert context.need_regenerate is False
    assert events[-2] == {"type": "delta", "content": context.response}
    assert "在这边" not in "".join(
        event.get("content", "") for event in events if event["type"] == "delta"
    )
    assert [message["content"] for message in loop.messages] == ["你好", context.response]


async def test_explicit_afterlife_question_keeps_relevant_reply():
    class AfterlifeLLM:
        async def stream(self, _messages):
            yield '{"reply":"我在这边挺好的，你放心。","instruct":"温柔地说"}'

    class NarrativePipeline(FakePipeline):
        async def run_postllm(self, ctx):
            return await QualityCheckModule().process(ctx)

    loop = AgentLoop(
        llm=AfterlifeLLM(),
        pipeline=NarrativePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
    )

    result = await loop.run_once("你在那边好吗")

    assert result.afterlife_topic_allowed is True
    assert result.response == "我在这边挺好的，你放心。"
