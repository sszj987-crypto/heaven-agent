import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.agent.context import PipelineContext
from src.agent.modules.postoutput.context_compress import ContextCompressModule


class TestContextCompressModule:
    def setup_method(self):
        self._module = ContextCompressModule()

        # Mock message_manager
        self._mock_messages = MagicMock()
        self._mock_messages.conversation_turns = 5
        self._mock_messages.conversation_chars = 1000
        self._mock_messages.conversation = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好啊"},
        ]

        # Mock llm_client - use AsyncMock directly for simplicity
        self._mock_llm = AsyncMock()
        self._mock_llm.chat.return_value = "对话摘要内容"

        self._module._set_deps(self._mock_llm, self._mock_messages)

    @pytest.mark.asyncio
    async def test_no_compress_when_under_threshold(self):
        ctx = PipelineContext(user_message="hi")
        result = await self._module.process(ctx)
        assert result is ctx
        self._mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_compress_when_over_turns(self):
        self._mock_messages.conversation_turns = 25  # > 20
        ctx = PipelineContext(user_message="hi")

        with patch("asyncio.create_task") as mock_create_task:
            await self._module.process(ctx)
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_triggers_compress_when_over_chars(self):
        self._mock_messages.conversation_chars = 25000  # > 20000
        ctx = PipelineContext(user_message="hi")

        with patch("asyncio.create_task") as mock_create_task:
            await self._module.process(ctx)
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_compress_calls_llm_with_conversation(self):
        self._mock_messages.conversation = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好啊"},
            {"role": "user", "content": "今天怎么样"},
            {"role": "assistant", "content": "挺好的"},
        ]
        await self._module._compress()

        self._mock_llm.chat.assert_called_once()
        call_messages = self._mock_llm.chat.call_args[0][0]
        assert call_messages[0]["role"] == "system"  # summary prompt
        assert "用户" in call_messages[1]["content"]

    @pytest.mark.asyncio
    async def test_compress_updates_message_manager(self):
        self._mock_messages.conversation = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "reply2"},
        ]
        await self._module._compress()

        # LLM 被调用并传入对话内容
        self._mock_llm.chat.assert_called_once()
        call_arg = self._mock_llm.chat.call_args[0][0]
        assert "msg1" in call_arg[1]["content"]

        # compress_conversation 被调用
        self._mock_messages.compress_conversation.assert_called_once()
        kwargs = self._mock_messages.compress_conversation.call_args[1]
        assert kwargs["summary"] == "对话摘要内容"
        assert kwargs["keep_recent"] == 2  # 4 - 2

    @pytest.mark.asyncio
    async def test_compress_handles_llm_failure(self):
        self._mock_llm.chat.side_effect = Exception("LLM error")
        self._mock_messages.conversation = [
            {"role": "user", "content": "msg"},
            {"role": "assistant", "content": "reply"},
        ]
        # 不应抛出异常
        await self._module._compress()
        self._mock_messages.compress_conversation.assert_not_called()

    def test_configure_updates_thresholds(self):
        ContextCompressModule.configure(max_turns=10, max_chars=5000)
        thresholds = ContextCompressModule.get_thresholds()
        assert thresholds["max_turns"] == 10
        assert thresholds["max_chars"] == 5000

        # 恢复默认值
        ContextCompressModule.configure(max_turns=20, max_chars=20000)
