import pytest
from src.agent.context import PipelineContext
from src.agent.modules.postllm.quality_check import QualityCheckModule


class TestQualityCheckModule:
    def setup_method(self):
        self._module = QualityCheckModule()

    @pytest.mark.asyncio
    async def test_pass_clean_response(self):
        ctx = PipelineContext(user_message="奶奶你好")
        ctx.response = "乖孩子，奶奶一直在呢。"
        ctx = await self._module.process(ctx)
        assert not ctx.need_regenerate

    @pytest.mark.asyncio
    async def test_detect_as_ai(self):
        ctx = PipelineContext(user_message="你是谁")
        ctx.response = "作为AI，我会尽力帮助你。"
        ctx.llm_messages = [{"role": "system", "content": "..."}]
        ctx = await self._module.process(ctx)
        assert ctx.need_regenerate is True

    @pytest.mark.asyncio
    async def test_detect_language_model(self):
        ctx = PipelineContext(user_message="hi")
        ctx.response = "我是语言模型，无法感知情感。"
        ctx.llm_messages = [{"role": "system", "content": "..."}]
        ctx = await self._module.process(ctx)
        assert ctx.need_regenerate is True

    @pytest.mark.asyncio
    async def test_detect_no_emotion(self):
        ctx = PipelineContext(user_message="hi")
        ctx.response = "我没有情感，所以无法理解你。"
        ctx.llm_messages = [{"role": "system", "content": "..."}]
        ctx = await self._module.process(ctx)
        assert ctx.need_regenerate is True

    @pytest.mark.asyncio
    async def test_appends_warning_messages(self):
        ctx = PipelineContext(user_message="你是谁")
        ctx.response = "作为AI..."
        ctx.llm_messages = [{"role": "system", "content": "system_prompt"}]
        ctx = await self._module.process(ctx)

        # 追加了警告 + 用户消息
        assert len(ctx.llm_messages) == 3
        assert "内部警告" in ctx.llm_messages[1]["content"]
        assert ctx.llm_messages[2]["content"] == "你是谁"

    @pytest.mark.asyncio
    async def test_empty_response_passes(self):
        ctx = PipelineContext(user_message="hi")
        ctx.response = ""
        ctx = await self._module.process(ctx)
        assert not ctx.need_regenerate

    @pytest.mark.asyncio
    async def test_all_forbidden_words_covered(self):
        ctx = PipelineContext(user_message="test")
        ctx.llm_messages = [{"role": "system", "content": "..."}]
        for word in QualityCheckModule._FORBIDDEN:
            ctx.need_regenerate = False
            ctx.response = f"xxx{word}yyy"
            ctx = await self._module.process(ctx)
            assert ctx.need_regenerate, f"Should detect: {word}"
