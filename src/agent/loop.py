import json
import time
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

# 默认语音语气（LLM 解析失败时使用）
_DEFAULT_INSTRUCT = "用平静自然的语气说话。"


def _parse_llm_response(raw: str) -> tuple[str, str]:
    """
    从 LLM 响应中提取 reply 和 instruct。
    期望 JSON 格式：{"reply": "...", "instruct": "..."}。
    解析失败时整段文本作为 reply，使用默认语气。
    """
    text = raw.strip()

    try:
        data = json.loads(text)
        reply = str(data.get("reply", "")).strip()
        instruct = str(data.get("instruct", _DEFAULT_INSTRUCT)).strip()
        if reply:
            log.debug("JSON 解析成功: reply=%d chars, instruct=%s", len(reply), instruct)
            return reply, instruct or _DEFAULT_INSTRUCT
        else:
            log.warning("JSON 中 reply 为空")
            return text, _DEFAULT_INSTRUCT
    except (json.JSONDecodeError, TypeError, AttributeError):
        log.warning("LLM 响应不是合法 JSON，使用原始文本作为回复")
        return text, _DEFAULT_INSTRUCT


class AgentLoop:
    """Agent 主循环：Input → PreLLM → LLM → PostLLM → PostOutput"""

    _MAX_REGENERATE = 2

    def __init__(self, llm_client: LLMClient, soul_loader: SoulLoader, circumstances: str = "", history_path: str = ""):
        self._llm = llm_client
        self._messages = MessageManager()
        self._soul_loader = soul_loader
        self._history_path = history_path

        if history_path:
            loaded = self._messages.load_from_file(history_path)
            if loaded:
                log.info("对话历史已从磁盘恢复, 轮数=%d", self._messages.conversation_turns)

        CircumstancesModule.update(circumstances)

        self._pipeline = Pipeline()

        SoulContextModule.set_deps(soul_loader, self._messages)
        ContextCompressModule.set_deps(llm_client, self._messages)
        MemoryPersistModule.set_deps(self._messages)

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        统一对话入口。
        返回: (reply_text, instruct_text)
        """
        t_start = time.monotonic()
        log.info("══════ AgentLoop.run 开始, user_message=%s ══════", user_message[:60])
        ctx = PipelineContext(user_message=user_message)

        # ── PreLLM ──
        t_prellm = time.monotonic()
        ctx = await self._pipeline.run_prellm(ctx)
        log.debug("PreLLM 耗时=%.2fs", time.monotonic() - t_prellm)

        # ── LLM（可能触发重生成）──
        for attempt in range(self._MAX_REGENERATE + 1):
            if attempt > 0:
                log.warning("LLM 重生成, attempt=%d/%d", attempt + 1, self._MAX_REGENERATE + 1)
            ctx.need_regenerate = False
            ctx.response = ""
            ctx.instruct_text = ""
            t_llm = time.monotonic()
            async for chunk in self._llm.stream(ctx.llm_messages):
                ctx.response += chunk
            log.debug("LLM 流式耗时=%.2fs", time.monotonic() - t_llm)
            log.debug("LLM 原始响应全文 (%d chars):\n%s", len(ctx.response), ctx.response)

            # 解析 LLM 响应：分离回复文本和语音语气
            reply, instruct = _parse_llm_response(ctx.response)
            ctx.response = reply
            ctx.instruct_text = instruct
            log.debug("解析后 reply (%d chars): %s", len(reply), reply[:300])
            log.debug("解析后 instruct: %s", instruct)

            ctx = await self._pipeline.run_postllm(ctx)

            if not ctx.need_regenerate:
                break

        # ── 记录对话历史 ──
        self._messages.add("user", user_message)
        self._messages.add("assistant", ctx.response)
        log.debug("对话历史更新, 轮数=%d, 总消息=%d, 对话字符=%d",
                  self._messages.conversation_turns, len(self._messages.get_all()),
                  self._messages.conversation_chars)

        if self._history_path:
            self._messages.save_to_file(self._history_path)

        # ── PostOutput ──
        ctx = await self._pipeline.run_postoutput(ctx)

        total_elapsed = time.monotonic() - t_start
        log.info("══════ AgentLoop.run 完成, 总耗时=%.2fs, reply_len=%d, instruct=%s, turns=%d ══════",
                 total_elapsed, len(ctx.response), ctx.instruct_text, self._messages.conversation_turns)

        yield ctx.response
        yield ctx.instruct_text

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
