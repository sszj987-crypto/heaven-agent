from ..base import PipelineModule
from ...context import PipelineContext
from ....config.logger import get_logger

log = get_logger("compress")

SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请用 2-3 句话概括以下对话的核心内容，"
    "保留关键信息：人名、事件、情绪变化、重要决定。"
)


class ContextCompressModule(PipelineModule):
    """每 crunch_interval 轮压缩一次上下文，用 LLM 摘要替换早期对话。

    - 保留最近 keep_recent 条对话消息
    - 其余 user/assistant 消息替换为一条摘要 system 消息
    - system 消息（soul context 等）完整保留
    """

    _llm = None
    _messages = None
    _store = None
    _compressing: bool = False
    _crunch_interval: int = 10
    _keep_recent: int = 6
    _job_manager = None

    @classmethod
    def set_deps(cls, llm_client, message_manager, store=None):
        cls._llm = llm_client
        cls._messages = message_manager
        cls._store = store

    @classmethod
    def configure(cls, crunch_interval: int = 10, keep_recent: int = 6):
        cls._crunch_interval = crunch_interval
        cls._keep_recent = keep_recent

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        turns = self._messages.conversation_turns

        if turns <= 0 or turns % self._crunch_interval != 0:
            return ctx

        if self._compressing:
            log.info("上下文压缩跳过: 上一轮压缩仍在进行中")
            return ctx

        log.info("触发上下文压缩, turns=%d, 总消息=%d", turns, len(self._messages.get_all()))
        # Must finish under AgentLoop's turn lock; a background mutation could
        # otherwise discard turns added while the summary LLM call is running.
        await self._compress()
        return ctx

    async def _compress(self):
        self._compressing = True
        try:
            conv = self._messages.conversation
            if len(conv) <= self._keep_recent:
                log.debug("对话消息不足, 跳过压缩, conv=%d, keep=%d", len(conv), self._keep_recent)
                return

            # 保留最近消息，压缩旧消息
            old_conv = conv[:-self._keep_recent]
            conversation_text = "\n".join(
                f"{'用户' if m['role'] == 'user' else '逝者'}: {m['content']}"
                for m in old_conv
            )
            summary_messages = [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": conversation_text},
            ]

            summary = await self._llm.chat(summary_messages)
            self._messages.compress_conversation(
                keep_recent=self._keep_recent,
                summary=summary,
            )
            log.info("上下文压缩完成, 摘要=%s...", summary[:80])

            # The summary remains in MessageManager as short-term conversation
            # context. It is model-generated and must never enter the semantic
            # profile-memory index as a source of character facts.
        except Exception as e:
            log.error("上下文压缩失败: %s", e)
        finally:
            self._compressing = False
