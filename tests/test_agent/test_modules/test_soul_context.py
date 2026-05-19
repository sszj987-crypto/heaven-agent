import pytest
from unittest.mock import MagicMock
from src.agent.context import PipelineContext
from src.agent.modules.prellm.soul_context import SoulContextModule
from src.soul.profile import SoulProfile


class TestSoulContextModule:
    def setup_method(self):
        SoulContextModule.invalidate()
        self._module = SoulContextModule()

        # Mock soul_loader
        profile = SoulProfile()
        profile.dimensions["basic_info"] = "# 基本信息\n## identity\nname: 王奶奶\n## description\n慈祥。"
        self._mock_loader = MagicMock()
        self._mock_loader.load.return_value = profile

        # Mock message_manager with history
        self._mock_messages = MagicMock()
        self._mock_messages.get_all.return_value = [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
        ]

        self._module._set_deps(self._mock_loader, self._mock_messages)

    @pytest.mark.asyncio
    async def test_builds_system_prompt_and_messages(self):
        ctx = PipelineContext(user_message="奶奶你好")
        ctx.circumstances = "清明节"
        ctx = await self._module.process(ctx)

        assert ctx.system_prompt != ""
        assert "王奶奶" in ctx.system_prompt

        # llm_messages: system + history + current
        assert len(ctx.llm_messages) == 4
        assert ctx.llm_messages[0]["role"] == "system"
        assert ctx.llm_messages[1]["role"] == "user"
        assert ctx.llm_messages[2]["role"] == "assistant"
        assert ctx.llm_messages[3]["role"] == "user"
        assert ctx.llm_messages[3]["content"] == "奶奶你好"

    @pytest.mark.asyncio
    async def test_caches_system_prompt(self):
        ctx1 = PipelineContext(user_message="hi")
        await self._module.process(ctx1)

        # 第二次调用不应再 load
        ctx2 = PipelineContext(user_message="hello")
        await self._module.process(ctx2)

        self._mock_loader.load.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_loader(self):
        ctx1 = PipelineContext(user_message="first")
        await self._module.process(ctx1)

        self._mock_loader.load.reset_mock()
        ctx2 = PipelineContext(user_message="second")
        await self._module.process(ctx2)

        self._mock_loader.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self):
        ctx1 = PipelineContext(user_message="first")
        await self._module.process(ctx1)

        SoulContextModule.invalidate()
        self._mock_loader.load.reset_mock()

        ctx2 = PipelineContext(user_message="second")
        await self._module.process(ctx2)

        self._mock_loader.load.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_history_works(self):
        self._mock_messages.get_all.return_value = []
        ctx = PipelineContext(user_message="first message")
        ctx = await self._module.process(ctx)

        assert len(ctx.llm_messages) == 2  # system + current only
