from typing import AsyncGenerator
from .pipeline import Pipeline
from .context import PipelineContext
from .message import MessageManager
from .modules import prellm as _prellm
from .modules import postllm as _postllm
from .modules import postoutput as _postoutput
from .modules.prellm.circumstances import CircumstancesModule
from .modules.prellm.soul_context import SoulContextModule
from .modules.postoutput.context_compress import ContextCompressModule
from .modules.postoutput.memory_persist import MemoryPersistModule
from ..llm.client import LLMClient
from ..soul.loader import SoulLoader


class AgentLoop:
    """Agent 主循环：Input → PreLLM → LLM → PostLLM → PostOutput"""

    _MAX_REGENERATE = 2  # 最多重生成次数

    def __init__(self, llm_client: LLMClient, soul_loader: SoulLoader, circumstances: str = ""):
        self._llm = llm_client
        self._messages = MessageManager()
        self._soul_loader = soul_loader

        # 设置初始场景
        CircumstancesModule.update(circumstances)

        # 构建 Pipeline（注册器自动收集所有 @Pipeline.register 模块）
        self._pipeline = Pipeline()

        # 注入依赖到需要外部资源的模块
        SoulContextModule()._set_deps(soul_loader, self._messages)
        ContextCompressModule()._set_deps(llm_client, self._messages)
        MemoryPersistModule()._set_deps(self._messages)

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        统一对话入口。
        返回: (response_text, tts_config)
        """
        ctx = PipelineContext(user_message=user_message)

        # ── PreLLM ──
        ctx = await self._pipeline.run_prellm(ctx)

        # ── LLM（可能触发重生成）──
        for _ in range(self._MAX_REGENERATE + 1):
            ctx.need_regenerate = False
            ctx.response = ""
            async for chunk in self._llm.stream(ctx.llm_messages):
                ctx.response += chunk

            ctx = await self._pipeline.run_postllm(ctx)

            if not ctx.need_regenerate:
                break

        # ── 记录对话历史 ──
        self._messages.add("user", user_message)
        self._messages.add("assistant", ctx.response)

        # ── PostOutput ──
        ctx = await self._pipeline.run_postoutput(ctx)

        yield ctx.response
        yield ctx.tts_config

    def invalidate_soul_cache(self):
        SoulContextModule.invalidate()

    @staticmethod
    def update_circumstances(circumstances: str):
        CircumstancesModule.update(circumstances)
