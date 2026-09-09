import asyncio
from types import SimpleNamespace

from src.agent.context import PipelineContext
from src.agent.loop import AgentLoop
from src.services.safety import SafetyPolicy


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
