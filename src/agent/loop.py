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
from .modules.prellm.soul_context import SoulContextModule
from .modules.prellm.circumstances import CircumstancesModule
from ..config.logger import get_logger

log = get_logger("agent")

# 默认语音语气（LLM 解析失败时使用）
_DEFAULT_INSTRUCT = "用平静自然的语气说话。"


def _parse_llm_response(raw: str) -> tuple[str, str]:
    """
    从 LLM 响应中提取 reply 和 instruct。
    期望 JSON 格式：{"reply": "..."}。
    解析失败时整段文本作为 reply，使用默认语气。
    """
    text = raw.strip()

    # 诊断日志：用 repr 显示不可见字符
    if text:
        log.debug("LLM 响应 (repr): %s", repr(text[:500]))
    else:
        log.warning("LLM 响应 strip 后为空, raw_len=%d, raw_repr=%s", len(raw), repr(raw[:200]))

    # 去除 markdown 代码块包裹（模型有时会忽略"不要用代码块"的指令）
    if text.startswith("```"):
        lines = text.split("\n")
        # 找到代码块结束位置
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip().startswith("```"):
                end_idx = i
                break
        if end_idx is not None:
            text = "\n".join(lines[1:end_idx]).strip()
            log.debug("去除 markdown 代码块后: %s", repr(text[:300]))
        elif len(lines) > 1:
            # 只有开头 ``` 没有结尾 ```，尝试去掉第一行
            text = "\n".join(lines[1:]).strip()
            log.debug("去除开头 ``` 后: %s", repr(text[:300]))

    # 尝试解析 JSON
    try:
        data = json.loads(text)
        reply = str(data.get("reply", "")).strip()
        instruct = str(data.get("instruct", _DEFAULT_INSTRUCT)).strip()
        if reply:
            log.debug("JSON 解析成功: reply=%d chars, instruct=%s", len(reply), instruct)
            return reply, instruct or _DEFAULT_INSTRUCT
        else:
            log.warning("JSON 中 reply 为空, raw=%s", repr(text[:200]))
            return text, _DEFAULT_INSTRUCT
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        log.warning("LLM 响应不是合法 JSON: %s, raw=%s", e, repr(text[:300]))
        return text, _DEFAULT_INSTRUCT


class AgentLoop:
    """Agent 主循环：Input → PreLLM → LLM → PostLLM → PostOutput"""

    _MAX_REGENERATE = 2

    def __init__(self, history_path: str = ""):
        from ..llm.manager import get_llm_client

        self._llm = get_llm_client()
        self._messages = MessageManager()
        self._history_path = history_path

        if history_path:
            loaded = self._messages.load_from_file(history_path)
            if loaded:
                log.info("对话历史已从磁盘恢复, 轮数=%d", self._messages.conversation_turns)

        self._pipeline = Pipeline()
        Pipeline.init_deps(self._messages)

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
