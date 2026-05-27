from pathlib import Path
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
from ..config.logger import get_logger

log = get_logger("agent")


class AgentLoop:
    """Agent 主循环：Input → PreLLM → LLM → PostLLM → PostOutput"""

    _MAX_REGENERATE = 2  # 最多重生成次数

    def __init__(self, llm_client: LLMClient, soul_loader: SoulLoader, circumstances: str = "", history_path: str = ""):
        self._llm = llm_client
        self._messages = MessageManager()
        self._soul_loader = soul_loader
        self._history_path = history_path

        # 从磁盘恢复对话历史
        if history_path:
            loaded = self._messages.load_from_file(history_path)
            if loaded:
                log.info("对话历史已从磁盘恢复, 轮数=%d", self._messages.conversation_turns)

        # 设置初始场景
        CircumstancesModule.update(circumstances)

        # 构建 Pipeline（注册器自动收集所有 @Pipeline.register 模块）
        self._pipeline = Pipeline()

        # 注入依赖到需要外部资源的模块
        SoulContextModule.set_deps(soul_loader, self._messages)
        ContextCompressModule.set_deps(llm_client, self._messages)
        MemoryPersistModule.set_deps(self._messages)

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        统一对话入口。
        返回: (response_text, tts_config)
        """
        log.info("AgentLoop.run 开始, user_message=%s...", user_message[:50])
        ctx = PipelineContext(user_message=user_message)

        # ── PreLLM ──
        log.debug("执行 PreLLM 阶段...")
        ctx = await self._pipeline.run_prellm(ctx)
        log.debug("PreLLM 完成, messages 数量=%d, emotion=%s",
                  len(ctx.llm_messages), ctx.emotion.type if ctx.emotion else "None")

        # ── LLM（可能触发重生成）──
        for attempt in range(self._MAX_REGENERATE + 1):
            if attempt > 0:
                log.warning("LLM 重生成, attempt=%d/%d", attempt + 1, self._MAX_REGENERATE + 1)
            ctx.need_regenerate = False
            ctx.response = ""
            log.debug("调用 LLM streaming, model=%s", self._llm.model)
            async for chunk in self._llm.stream(ctx.llm_messages):
                ctx.response += chunk
            log.debug("LLM 响应完成, 长度=%d 字符", len(ctx.response))

            ctx = await self._pipeline.run_postllm(ctx)

            if not ctx.need_regenerate:
                break
            log.debug("LLM 响应触发重生成规则")

        # ── 记录对话历史 ──
        self._messages.add("user", user_message)
        self._messages.add("assistant", ctx.response)
        log.debug("对话历史更新, 轮数=%d, 总字符=%d",
                  self._messages.conversation_turns, self._messages.conversation_chars)

        # 每次对话后落盘
        if self._history_path:
            self._messages.save_to_file(self._history_path)
            log.debug("对话历史已保存到 %s", self._history_path)

        # ── PostOutput ──
        log.debug("执行 PostOutput 阶段...")
        ctx = await self._pipeline.run_postoutput(ctx)
        log.debug("PostOutput 完成")

        yield ctx.response
        yield ctx.tts_config

    def invalidate_soul_cache(self):
        SoulContextModule.invalidate()

    @property
    def messages(self) -> list[dict]:
        """返回对话历史（供 API 使用）"""
        return self._messages.get_all()

    def delete_history(self) -> None:
        """清空内存中的对话历史，并删除磁盘上的 conversation.json"""
        self._messages.clear()
        if self._history_path:
            p = Path(self._history_path)
            if p.exists():
                p.unlink()
                log.info("对话历史文件已删除: %s", p)

    @staticmethod
    def update_circumstances(circumstances: str):
        CircumstancesModule.update(circumstances)
