import pytest
from unittest.mock import MagicMock, AsyncMock
from src.agent.context import PipelineContext
from src.agent.modules.postoutput.context_compress import ContextCompressModule


class TestContextCompressModule:
    def setup_method(self):
        self._module = ContextCompressModule()

        self._mock_messages = MagicMock()
        self._mock_messages.conversation_turns = 5
        self._mock_messages.conversation = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好啊"},
        ]

        self._mock_llm = AsyncMock()
        self._mock_llm.chat.return_value = "对话摘要内容"

        self._module.set_deps(self._mock_llm, self._mock_messages)

    @pytest.mark.asyncio
    async def test_no_compress_when_not_at_interval(self):
        """不在间隔轮数时不触发压缩。"""
        self._mock_messages.conversation_turns = 7  # 7 % 10 != 0
        ctx = PipelineContext(user_message="hi")
        result = await self._module.process(ctx)
        assert result is ctx
        self._mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_compress_at_interval(self):
        """压缩必须在当前回合内完成，避免后台任务覆盖后续消息。"""
        self._mock_messages.conversation_turns = 10  # _crunch_interval default
        self._mock_messages.conversation = [
            {"role": "user", "content": f"msg-{index}"}
            for index in range(8)
        ]
        ctx = PipelineContext(user_message="hi")

        await self._module.process(ctx)

        self._mock_llm.chat.assert_awaited_once()
        self._mock_messages.compress_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_already_compressing(self):
        """上一次压缩未完成时跳过。"""
        self._module._compressing = True
        self._mock_messages.conversation_turns = 10  # _crunch_interval default
        ctx = PipelineContext(user_message="hi")

        await self._module.process(ctx)
        self._mock_llm.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compress_calls_llm_with_conversation(self):
        self._mock_messages.conversation = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好啊"},
            {"role": "user", "content": "今天怎么样"},
            {"role": "assistant", "content": "挺好的"},
            {"role": "user", "content": "不错"},
            {"role": "assistant", "content": "是啊"},
            {"role": "user", "content": "嗯"},
            {"role": "assistant", "content": "好"},
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
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "reply3"},
            {"role": "user", "content": "msg4"},
            {"role": "assistant", "content": "reply4"},
            {"role": "user", "content": "msg5"},
            {"role": "assistant", "content": "reply5"},
        ]  # 10 messages, > KEEP_RECENT=6
        await self._module._compress()

        self._mock_llm.chat.assert_called_once()
        self._mock_messages.compress_conversation.assert_called_once()
        kwargs = self._mock_messages.compress_conversation.call_args[1]
        assert kwargs["summary"] == "对话摘要内容"
        assert kwargs["keep_recent"] == 6  # KEEP_RECENT

    @pytest.mark.asyncio
    async def test_compress_skips_when_few_messages(self):
        """对话消息不足时不压缩。"""
        self._mock_messages.conversation = [
            {"role": "user", "content": "msg"},
            {"role": "assistant", "content": "reply"},
        ]  # 2 < KEEP_RECENT=6
        await self._module._compress()
        self._mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_compress_handles_llm_failure(self):
        self._mock_llm.chat.side_effect = Exception("LLM error")
        self._mock_messages.conversation = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "reply2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "reply3"},
            {"role": "user", "content": "msg4"},
            {"role": "assistant", "content": "reply4"},
            {"role": "user", "content": "msg5"},
            {"role": "assistant", "content": "reply5"},
        ]
        # 不应抛出异常
        await self._module._compress()
        self._mock_messages.compress_conversation.assert_not_called()
