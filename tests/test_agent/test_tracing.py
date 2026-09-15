import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from src.agent.loop import AgentLoop
from src.config.logger import get_level, set_level
from src.observability import bind_request_id, current_request_id, reset_request_id


class TracePipeline:
    async def run_prellm(self, ctx):
        ctx.llm_messages = [{"role": "user", "content": ctx.user_message}]
        ctx.retrieved_memories = [{"id": "memory-1"}]
        ctx.context_budget = {
            "input_chars": 120,
            "output_chars": 80,
            "dropped_history_messages": 2,
            "system_compacted": True,
            "overflow_chars": 0,
        }
        return ctx

    async def run_postllm(self, ctx):
        return ctx

    async def run_postoutput(self, ctx):
        return ctx


class TraceLLM:
    model = "local-test-model"

    async def stream(self, _messages):
        yield '{"reply":"私密回复","instruct":"温柔地说"}'


def _tracer_and_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("heaven-agent-test"), exporter


async def test_turn_trace_covers_agent_stages_without_recording_content():
    tracer, exporter = _tracer_and_exporter()
    loop = AgentLoop(
        llm=TraceLLM(),
        pipeline=TracePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
        tracer=tracer,
    )
    private_input = "这是不能进入追踪的私密输入"
    request_id_token = bind_request_id("request-123")
    try:
        result = await loop.run_once(private_input)
    finally:
        reset_request_id(request_id_token)

    assert result.response == "私密回复"
    spans = exporter.get_finished_spans()
    by_name = {span.name: span for span in spans}
    assert set(by_name) == {
        "heaven.agent.turn",
        "heaven.agent.safety",
        "heaven.agent.prellm",
        "heaven.agent.llm.generate",
        "heaven.agent.output.parse",
        "heaven.agent.postllm",
        "heaven.agent.history.persist",
        "heaven.agent.postoutput",
    }

    turn = by_name["heaven.agent.turn"]
    assert turn.parent is None
    assert turn.attributes["heaven.request.id"] == "request-123"
    assert turn.attributes["heaven.agent.input_chars"] == len(private_input)
    assert turn.attributes["heaven.agent.output_chars"] == len(result.response)
    assert by_name["heaven.agent.prellm"].attributes[
        "heaven.agent.retrieved_memory_count"
    ] == 1
    assert by_name["heaven.agent.prellm"].attributes[
        "heaven.agent.context.dropped_history_messages"
    ] == 2
    assert by_name["heaven.agent.prellm"].attributes[
        "heaven.agent.context.system_compacted"
    ] is True
    assert by_name["heaven.agent.llm.generate"].attributes[
        "gen_ai.request.model"
    ] == "local-test-model"

    root_span_id = turn.context.span_id
    assert all(
        span.parent is not None and span.parent.span_id == root_span_id
        for span in spans
        if span.name != "heaven.agent.turn"
    )

    recorded_metadata = repr(
        [(span.attributes, span.events) for span in spans]
    )
    assert private_input not in recorded_metadata
    assert "私密回复" not in recorded_metadata
    assert "温柔地说" not in recorded_metadata


async def test_trace_records_error_type_without_exception_message_or_content():
    class FailingLLM:
        model = "local-test-model"

        async def stream(self, _messages):
            raise RuntimeError("provider leaked 私密输入")
            yield ""

    tracer, exporter = _tracer_and_exporter()
    loop = AgentLoop(
        llm=FailingLLM(),
        pipeline=TracePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
        tracer=tracer,
    )

    with pytest.raises(RuntimeError, match="provider leaked"):
        await loop.run_once("私密输入")

    spans = exporter.get_finished_spans()
    by_name = {span.name: span for span in spans}
    assert by_name["heaven.agent.llm.generate"].status.status_code is StatusCode.ERROR
    assert by_name["heaven.agent.turn"].status.status_code is StatusCode.ERROR
    assert by_name["heaven.agent.llm.generate"].attributes["error.type"] == "RuntimeError"
    assert by_name["heaven.agent.turn"].attributes["error.type"] == "RuntimeError"
    assert all(not span.events for span in spans)
    recorded_metadata = repr([span.attributes for span in spans])
    assert "provider leaked" not in recorded_metadata
    assert "私密输入" not in recorded_metadata


async def test_closing_a_stream_early_finishes_open_spans_cleanly():
    tracer, exporter = _tracer_and_exporter()
    loop = AgentLoop(
        llm=TraceLLM(),
        pipeline=TracePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
        tracer=tracer,
    )
    stream = loop.stream_once("提前结束")

    first_event = await anext(stream)
    assert first_event["type"] == "delta"
    await stream.aclose()

    spans = exporter.get_finished_spans()
    assert {span.name for span in spans} >= {
        "heaven.agent.turn",
        "heaven.agent.llm.generate",
    }
    assert all(span.status.status_code is not StatusCode.ERROR for span in spans)


async def test_debug_mode_logs_key_stages_without_conversation_content(caplog):
    tracer, _exporter = _tracer_and_exporter()
    loop = AgentLoop(
        llm=TraceLLM(),
        pipeline=TracePipeline(),
        max_conversation_turns=20,
        max_regenerate=0,
        tracer=tracer,
    )
    private_input = "日志里不能出现的私密输入"
    previous_level = get_level()
    set_level("debug")
    caplog.set_level(logging.DEBUG, logger="heaven")
    try:
        await loop.run_once(private_input)
    finally:
        set_level(previous_level)

    debug_output = "\n".join(record.getMessage() for record in caplog.records)
    for stage in (
        "stage=turn",
        "stage=safety",
        "stage=prellm",
        "stage=llm_generate",
        "stage=output_parse",
        "stage=postllm",
        "stage=history_persist",
        "stage=postoutput",
    ):
        assert stage in debug_output
    assert "duration_ms=" in debug_output
    assert "turn_id=" in debug_output
    assert private_input not in debug_output
    assert "私密回复" not in debug_output
    assert "温柔地说" not in debug_output


def test_request_id_context_is_restored_after_reset():
    assert current_request_id() is None
    token = bind_request_id("request-456")
    assert current_request_id() == "request-456"
    reset_request_id(token)
    assert current_request_id() is None
