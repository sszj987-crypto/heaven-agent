"""MemoryExtractModule 单元测试"""

import pytest

from src.agent.modules.postoutput.memory_extract import (
    MemoryExtractModule,
    _MEMORY_DIMENSION_LABELS,
)
from src.agent.context import PipelineContext


class TestExtractTrigger:
    """测试提取触发条件：轮数阈值 + 防重入"""

    async def test_triggers_at_threshold(self):
        """达到阈值轮数时触发提取。"""
        module = MemoryExtractModule()
        module._last_extracted_turn = 0

        # 模拟 message_manager
        class FakeMessages:
            conversation_turns = 5
            conversation = [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好呀"},
                {"role": "user", "content": "今天怎么样"},
                {"role": "assistant", "content": "挺好的"},
                {"role": "user", "content": "你最近在做什么"},
                {"role": "assistant", "content": "在学画画"},
                {"role": "user", "content": "好玩吗"},
                {"role": "assistant", "content": "很有意思"},
                {"role": "user", "content": "我也想学"},
                {"role": "assistant", "content": "可以试试"},
            ]

        module._messages = FakeMessages()
        module._store = None  # 不实际写入

        ctx = PipelineContext(user_message="可以试试")
        ctx.soul_profile = type("FakeProfile", (), {"name": "测试者"})()

        result = await module.process(ctx)
        assert result is ctx

    async def test_skips_below_threshold(self):
        """轮数不足时不触发。"""
        module = MemoryExtractModule()
        module._last_extracted_turn = 0

        class FakeMessages:
            conversation_turns = 3
            conversation = [
                {"role": "user", "content": "嗨"},
                {"role": "assistant", "content": "嗨"},
            ]

        module._messages = FakeMessages()

        ctx = PipelineContext(user_message="嗨")
        result = await module.process(ctx)
        assert result is ctx
        assert module._extracting is False

    async def test_skips_when_already_extracting(self):
        """上一次提取未完成时跳过。"""
        module = MemoryExtractModule()
        module._extracting = True
        module._last_extracted_turn = 0

        class FakeMessages:
            conversation_turns = 5
            conversation = [{"role": "user", "content": "x"}] * 10

        module._messages = FakeMessages()

        ctx = PipelineContext(user_message="x")
        result = await module.process(ctx)
        assert result is ctx


class TestPromptFormat:
    """测试提取 prompt 格式"""

    def test_build_prompt_contains_soul_name(self):
        module = MemoryExtractModule()
        history = [
            {"role": "user", "content": "你好吗"},
            {"role": "assistant", "content": "我很好"},
        ]
        prompt = module._build_prompt("小明", history)
        assert "小明" in prompt
        assert "记忆管家" in prompt

    def test_build_prompt_contains_dimensions(self):
        module = MemoryExtractModule()
        history = [
            {"role": "user", "content": "你喜欢什么"},
            {"role": "assistant", "content": "我喜欢钓鱼"},
        ]
        prompt = module._build_prompt("小明", history)
        for key, label in _MEMORY_DIMENSION_LABELS.items():
            assert key in prompt
            assert label in prompt

    def test_build_prompt_contains_history(self):
        module = MemoryExtractModule()
        history = [
            {"role": "user", "content": "你好吗"},
            {"role": "assistant", "content": "我很好"},
        ]
        prompt = module._build_prompt("小红", history)
        assert "你好吗" in prompt
        assert "我很好" in prompt

    def test_build_prompt_empty_history(self):
        module = MemoryExtractModule()
        prompt = module._build_prompt("小明", [])
        assert "小明" in prompt
        # 空对话不影响 prompt 生成


class TestParseResult:
    """测试 LLM 返回结果解析"""

    def test_parse_valid_array(self):
        module = MemoryExtractModule()
        raw = '[{"dimension": "hobbies", "content": "喜欢钓鱼", "keywords": ["钓鱼"]}]'
        result = module._parse_result(raw)
        assert len(result) == 1
        assert result[0]["dimension"] == "hobbies"
        assert result[0]["content"] == "喜欢钓鱼"

    def test_parse_empty_array(self):
        module = MemoryExtractModule()
        result = module._parse_result("[]")
        assert result == []

    def test_parse_with_markdown_code_block(self):
        module = MemoryExtractModule()
        raw = '```json\n[{"dimension": "hobbies", "content": "喜欢钓鱼"}]\n```'
        result = module._parse_result(raw)
        assert len(result) == 1
        assert result[0]["content"] == "喜欢钓鱼"

    def test_parse_wrapped_in_object(self):
        module = MemoryExtractModule()
        raw = '{"facts": [{"dimension": "hobbies", "content": "钓鱼"}]}'
        result = module._parse_result(raw)
        assert len(result) == 1
        assert result[0]["dimension"] == "hobbies"

    def test_parse_invalid_json_returns_empty(self):
        module = MemoryExtractModule()
        result = module._parse_result("这不是 JSON")
        assert result == []

    def test_parse_multiple_facts(self):
        module = MemoryExtractModule()
        raw = (
            '['
            '{"dimension": "hobbies", "content": "钓鱼", "keywords": ["钓鱼"]},'
            '{"dimension": "life_experiences", "content": "2020年去了西藏", "keywords": ["西藏", "旅行"]}'
            ']'
        )
        result = module._parse_result(raw)
        assert len(result) == 2


class TestDimensionLabels:
    """测试记忆维度标签与 MemorySynchronizer 一致"""

    def test_labels_match_memory_dimensions(self):
        from src.memory.sync import MEMORY_DIMENSIONS
        assert set(_MEMORY_DIMENSION_LABELS.keys()) == MEMORY_DIMENSIONS

    def test_all_labels_are_non_empty(self):
        for key, label in _MEMORY_DIMENSION_LABELS.items():
            assert label, f"维度 {key} 缺少中文标签"
