from dataclasses import asdict

from ..base import PipelineModule
from ...context import PipelineContext
from ...context_budget import ContextBudgeter
from ....config.logger import get_logger

log = get_logger("soul_context")


class SoulContextModule(PipelineModule):
    """加载 Soul Profile + 对话历史 → 构建完整 messages（最后执行）"""

    _cached_prompt: str | None = None  # System Prompt 缓存
    _loader = None
    _messages = None
    _builder = None
    _dialect_settings = None
    _max_context_chars: int = 24_000

    @classmethod
    def set_deps(cls, soul_loader, message_manager):
        """注入依赖（由 AgentLoop 初始化时调用）"""
        cls._loader = soul_loader
        cls._messages = message_manager
        cls._builder = None
        cls._dialect_settings = None
        cls._max_context_chars = 24_000

    @property
    def _prompt_builder(self):
        if self._builder is None:
            from ....soul.prompt_builder import SoulPromptBuilder
            self._builder = SoulPromptBuilder()
        return self._builder

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        circumstances = ctx.circumstances or ""
        log.info("Soul Context 构建开始, circumstances=%s", circumstances[:60] if circumstances else "无")

        # 加载 profile（后续模块依赖 ctx.soul_profile，需始终设置）
        profile = self._loader.load()
        ctx.soul_profile = profile

        # 场景与检索记忆是逐轮动态数据，不能缓存进完整 System Prompt。
        # 后续如需优化，只能缓存不含 circumstances/memories 的静态人格片段。
        skill_card = self._loader.load_skill() if self._loader.has_skill() else None
        memories = getattr(ctx, "retrieved_memories", None) or []
        dialect = self._dialect_settings.load() if self._dialect_settings is not None else None
        ctx.system_prompt = self._prompt_builder.build(
            profile,
            circumstances,
            skill_card,
            memories,
            afterlife_topic_allowed=ctx.afterlife_topic_allowed,
        )
        log.info("构建 System Prompt, soul=%s, 长度=%d chars, has_skill=%s, memories=%d",
                 profile.name, len(ctx.system_prompt),
                 bool(skill_card and skill_card.has_content), len(memories))

        # 组装 messages: system + 历史消息 + 当前消息
        history = self._messages.get_all()
        dialect_instruction = dialect.text_instruction if dialect is not None else ""
        ctx.dialect_text_instruction = dialect_instruction
        budgeted = ContextBudgeter(self._max_context_chars).build(
            system_prompt=ctx.system_prompt,
            history=history,
            current_user=ctx.user_message,
            dialect_instruction=dialect_instruction,
        )
        ctx.llm_messages = budgeted.messages
        ctx.context_budget = asdict(budgeted.stats)
        selected_system = ctx.llm_messages[0]["content"]
        memory_count_before_budget = len(ctx.retrieved_memories)
        if budgeted.stats.system_compacted and ctx.retrieved_memories:
            ctx.retrieved_memories = [
                memory
                for memory in ctx.retrieved_memories
                if str(memory.get("document", "")) in selected_system
            ]
        ctx.context_budget["dropped_retrieved_memories"] = (
            memory_count_before_budget - len(ctx.retrieved_memories)
        )
        log.info("Soul Context 构建完成, system=%d chars, history=%d msgs, current_msg=%d chars, total_msgs=%d",
                 len(ctx.system_prompt), len(history), len(ctx.user_message), len(ctx.llm_messages))
        log.info(
            "上下文预算, max=%d, before=%d, after=%d, system_compacted=%s, "
            "history_dropped=%d, overflow=%d",
            budgeted.stats.max_chars,
            budgeted.stats.input_chars,
            budgeted.stats.output_chars,
            budgeted.stats.system_compacted,
            budgeted.stats.dropped_history_messages,
            budgeted.stats.overflow_chars,
        )
        # 此处记录预算结构；LLM client 会在 DEBUG 下输出实际发送的完整正文。
        if log.isEnabledFor(10):
            log.debug("── LLM 输入结构（total=%d msgs）──", len(ctx.llm_messages))
            log.debug(
                "方言指令: enabled=%s, placement=%s",
                bool(dialect_instruction),
                "before_current_user" if dialect_instruction else "none",
            )
            for i, msg in enumerate(ctx.llm_messages):
                log.debug("[%d/%d] role=%s, len=%d",
                         i + 1, len(ctx.llm_messages), msg["role"], len(msg["content"]))
            total_chars = sum(len(m["content"]) for m in ctx.llm_messages)
            log.debug("── LLM 输入结构结束（total=%d msgs, %d chars）──",
                     len(ctx.llm_messages), total_chars)
        return ctx

    @classmethod
    def invalidate(cls):
        """Soul 维度更新后使缓存失效"""
        cls._cached_prompt = None
        log.debug("System Prompt 缓存已失效")
