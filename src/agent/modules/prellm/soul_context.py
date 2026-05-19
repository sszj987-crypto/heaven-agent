from ..base import PipelineModule
from ...context import PipelineContext
from ...pipeline import Pipeline


@Pipeline.register(slot="prellm", order=3)
class SoulContextModule(PipelineModule):
    """加载 Soul Profile + 对话历史 → 构建完整 messages（最后执行）"""

    _cached_prompt: str | None = None  # System Prompt 缓存

    def _set_deps(self, soul_loader, message_manager):
        """注入依赖（由 AgentLoop 初始化时调用）"""
        self._loader = soul_loader
        self._builder = None  # 延迟导入避免循环
        self._messages = message_manager

    @property
    def _prompt_builder(self):
        if self._builder is None:
            from ....soul.prompt_builder import SoulPromptBuilder
            self._builder = SoulPromptBuilder()
        return self._builder

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        circumstances = ctx.circumstances or ""

        # 构建 System Prompt（带缓存）
        if SoulContextModule._cached_prompt is not None:
            ctx.system_prompt = SoulContextModule._cached_prompt
        else:
            profile = self._loader.load()
            ctx.soul_profile = profile
            ctx.system_prompt = self._prompt_builder.build(profile, circumstances)
            SoulContextModule._cached_prompt = ctx.system_prompt

        # 组装 messages: system + 历史消息 + 当前消息
        ctx.llm_messages = [{"role": "system", "content": ctx.system_prompt}]
        ctx.llm_messages.extend(self._messages.get_all())
        ctx.llm_messages.append({"role": "user", "content": ctx.user_message})
        return ctx

    @classmethod
    def invalidate(cls):
        """Soul 维度更新后使缓存失效"""
        cls._cached_prompt = None
