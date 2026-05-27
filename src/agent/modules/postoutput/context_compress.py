from ..base import PipelineModule
from ...context import PipelineContext
from ...pipeline import Pipeline
from ....config.logger import get_logger

log = get_logger("compress")

DEFAULT_MAX_TURNS = 20       # 超过 20 轮触发压缩
DEFAULT_MAX_CHARS = 20_000   # 对话字符数超过 20k 触发压缩
SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请用 2-3 句话概括以下对话的核心内容，"
    "保留关键信息：人名、事件、情绪变化、重要决定。"
)


@Pipeline.register(slot="postoutput", order=1)
class ContextCompressModule(PipelineModule):
    """
    上下文压缩模块。
    仅对 user/assistant 对话消息做压缩，system 消息（soul context 等）完整保留。
    检测对话是否超过轮数/长度阈值，超限时异步调用 LLM 生成摘要，
    用摘要替换早期对话消息，保持上下文在预算内。
    """

    _max_turns: int = DEFAULT_MAX_TURNS
    _max_chars: int = DEFAULT_MAX_CHARS
    _llm = None
    _messages = None

    @classmethod
    def set_deps(cls, llm_client, message_manager):
        cls._llm = llm_client
        cls._messages = message_manager

    @classmethod
    def configure(cls, max_turns: int = 20, max_chars: int = 20_000):
        """配置压缩阈值"""
        cls._max_turns = max_turns
        cls._max_chars = max_chars

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        turns = self._messages.conversation_turns
        chars = self._messages.conversation_chars
        log.info("上下文压缩检查, turns=%d/%d, chars=%d/%d",
                 turns, self._max_turns, chars, self._max_chars)

        if turns <= self._max_turns and chars <= self._max_chars:
            log.debug("无需压缩, 未达阈值")
            return ctx  # 未超阈值，不压缩

        log.info("触发上下文压缩, turns=%d, chars=%d, 总消息=%d", turns, chars, len(self._messages.get_all()))
        # 异步触发摘要（不阻塞当前回复）
        import asyncio
        asyncio.create_task(self._compress())
        return ctx

    async def _compress(self):
        """仅压缩 user/assistant 对话，system 消息完整保留"""
        conv = self._messages.conversation
        half = len(conv) // 2
        old_conv = conv[:half]

        # 构建摘要请求
        conversation_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else '逝者'}: {m['content']}"
            for m in old_conv
        )
        summary_messages = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": conversation_text},
        ]

        try:
            summary = await self._llm.chat(summary_messages)
            self._messages.compress_conversation(
                keep_recent=len(conv) - half,
                summary=summary,
            )
            log.info("上下文压缩完成, 摘要=%s...", summary[:50])
        except Exception as e:
            log.error("上下文压缩失败: %s", e)

    @classmethod
    def get_thresholds(cls) -> dict:
        return {"max_turns": cls._max_turns, "max_chars": cls._max_chars}
