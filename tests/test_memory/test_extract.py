"""MemoryExtractModule 单元测试（人物信息提取 → soul MD 更新）"""

import pytest

from src.agent.modules.postoutput.memory_extract import (
    MemoryExtractModule,
    _PERSON_DIMENSIONS,
)
from src.agent.context import PipelineContext


class TestExtractTrigger:
    """测试提取触发条件：间隔轮数 + 防重入"""

    async def test_triggers_at_interval(self):
        """达到间隔轮数（10 的倍数）时触发提取。"""
        module = MemoryExtractModule()

        class FakeMessages:
            conversation_turns = 10
            conversation = [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好呀"},
            ] * 8

        module._messages = FakeMessages()

        ctx = PipelineContext(user_message="可以试试")
        ctx.soul_profile = type("FakeProfile", (), {"name": "测试者"})()

        result = await module.process(ctx)
        assert result is ctx

    async def test_skips_not_at_interval(self):
        """不在间隔轮数时不触发。"""
        module = MemoryExtractModule()

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

        class FakeMessages:
            conversation_turns = 10
            conversation = [{"role": "user", "content": "x"}] * 20

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
        for key, label in _PERSON_DIMENSIONS.items():
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

    def test_build_prompt_has_conservative_wording(self):
        """提示词包含谨慎提取的要求。"""
        module = MemoryExtractModule()
        history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好"}]
        prompt = module._build_prompt("小明", history)
        assert "宁可漏过" in prompt


class TestParseResult:
    """测试 LLM 返回结果解析"""

    def test_parse_valid_array(self):
        module = MemoryExtractModule()
        raw = '[{"dimension": "personal_traits", "content": "喜欢钓鱼"}]'
        result = module._parse_result(raw)
        assert len(result) == 1
        assert result[0]["dimension"] == "personal_traits"
        assert result[0]["content"] == "喜欢钓鱼"

    def test_parse_empty_array(self):
        module = MemoryExtractModule()
        result = module._parse_result("[]")
        assert result == []

    def test_parse_with_markdown_code_block(self):
        module = MemoryExtractModule()
        raw = '```json\n[{"dimension": "personal_traits", "content": "喜欢钓鱼"}]\n```'
        result = module._parse_result(raw)
        assert len(result) == 1
        assert result[0]["content"] == "喜欢钓鱼"

    def test_parse_wrapped_in_object(self):
        module = MemoryExtractModule()
        raw = '{"facts": [{"dimension": "personal_traits", "content": "钓鱼"}]}'
        result = module._parse_result(raw)
        assert len(result) == 1
        assert result[0]["dimension"] == "personal_traits"

    def test_parse_invalid_json_returns_empty(self):
        module = MemoryExtractModule()
        result = module._parse_result("这不是 JSON")
        assert result == []

    def test_parse_multiple_facts(self):
        module = MemoryExtractModule()
        raw = (
            '['
            '{"dimension": "personal_traits", "content": "钓鱼"},'
            '{"dimension": "life_experiences", "content": "2020年去了西藏"}'
            ']'
        )
        result = module._parse_result(raw)
        assert len(result) == 2


class TestPersonDimensions:

    def test_all_dimensions_have_labels(self):
        for key, label in _PERSON_DIMENSIONS.items():
            assert label, f"维度 {key} 缺少中文标签"


class TestAppendDimension:
    """测试追加维度内容到 soul 文件"""

    def test_append_to_empty_dimension(self):
        """空维度追加内容。"""
        module = MemoryExtractModule()

        class FakeLoader:
            def __init__(self):
                self.saved = {}

            def load_dimension(self, dim):
                return self.saved.get(dim, "")

            def save_dimension(self, dim, content):
                self.saved[dim] = content

        loader = FakeLoader()
        module._loader = loader

        module._append_to_dimension("personal_traits", "喜欢钓鱼")
        saved = loader.load_dimension("personal_traits")
        assert saved == "\n- 喜欢钓鱼\n"

    def test_append_to_existing_dimension(self):
        """已有内容的维度追加。"""
        module = MemoryExtractModule()

        class FakeLoader:
            def __init__(self):
                self.saved = {"personal_traits": "# 个人特质\n\n- 喜欢画画\n"}

            def load_dimension(self, dim):
                return self.saved.get(dim, "")

            def save_dimension(self, dim, content):
                self.saved[dim] = content

        loader = FakeLoader()
        module._loader = loader

        module._append_to_dimension("personal_traits", "擅长烹饪")
        saved = loader.load_dimension("personal_traits")
        assert "喜欢画画" in saved
        assert "擅长烹饪" in saved
