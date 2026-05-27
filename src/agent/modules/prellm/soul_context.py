from ..base import PipelineModule
from ...context import PipelineContext
from ...pipeline import Pipeline
from ....config.logger import get_logger

log = get_logger("soul_context")


@Pipeline.register(slot="prellm", order=3)
class SoulContextModule(PipelineModule):
    """加载 Soul Profile + 对话历史 → 构建完整 messages（最后执行）"""

    _cached_prompt: str | None = None  # System Prompt 缓存
    _loader = None
    _messages = None
    _builder = None

    @classmethod
    def set_deps(cls, soul_loader, message_manager):
        """注入依赖（由 AgentLoop 初始化时调用）"""
        cls._loader = soul_loader
        cls._messages = message_manager
        cls._builder = None

    @property
    def _prompt_builder(self):
        if SoulContextModule._builder is None:
            from ....soul.prompt_builder import SoulPromptBuilder
            SoulContextModule._builder = SoulPromptBuilder()
        return SoulContextModule._builder

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        circumstances = ctx.circumstances or ""

        # 构建 System Prompt（带缓存）
        if SoulContextModule._cached_prompt is not None:
            ctx.system_prompt = SoulContextModule._cached_prompt
            log.debug("使用缓存的 System Prompt, 长度=%d", len(ctx.system_prompt))
        else:
            profile = self._loader.load()
            ctx.soul_profile = profile
            ctx.system_prompt = self._prompt_builder.build(profile, circumstances)
            SoulContextModule._cached_prompt = ctx.system_prompt
            log.debug("构建新 System Prompt, 长度=%d, dimensions=%d",
                      len(ctx.system_prompt), len(profile.dimensions))

        # 组装 messages: system + 历史消息 + 当前消息
        history = self._messages.get_all()
        ctx.llm_messages = [{"role": "system", "content": ctx.system_prompt}]
        ctx.llm_messages.extend(history)
        ctx.llm_messages.append({"role": "user", "content": ctx.user_message})
        log.debug("组装 LLM messages, system=%d chars, history=%d, total=%d",
                  len(ctx.system_prompt), len(history), len(ctx.llm_messages))
        return ctx

    @classmethod
    def invalidate(cls):
        """Soul 维度更新后使缓存失效"""
        cls._cached_prompt = None
        log.debug("System Prompt 缓存已失效")
