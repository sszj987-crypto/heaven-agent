import json
import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator
from .pipeline import Pipeline
from .context import PipelineContext
from .message import MessageManager
from .modules import prellm as _prellm
from .modules import postllm as _postllm
from .modules import postoutput as _postoutput
from ..config.logger import get_logger

log = get_logger("agent")

# 默认语音语气（LLM 解析失败时使用）
_DEFAULT_INSTRUCT = "用平静自然的语气说话。"


class _ReplyStreamDecoder:
    """Extract the JSON ``reply`` string as the model produces it."""

    def __init__(self):
        self._raw = ""
        self._position = 0
        self._started = False
        self._finished = False
        self._escaped = False
        self._unicode = ""

    def feed(self, chunk: str) -> str:
        self._raw += chunk
        if not self._started:
            marker = '"reply"'
            key = self._raw.find(marker)
            if key < 0:
                return ""
            colon = self._raw.find(":", key + len(marker))
            if colon < 0:
                return ""
            quote = self._raw.find('"', colon + 1)
            if quote < 0:
                return ""
            self._started = True
            self._position = quote + 1

        output: list[str] = []
        while self._position < len(self._raw) and not self._finished:
            char = self._raw[self._position]
            self._position += 1
            if self._unicode:
                self._unicode += char
                if len(self._unicode) == 6:
                    try:
                        output.append(chr(int(self._unicode[2:], 16)))
                    except ValueError:
                        output.append(self._unicode)
                    self._unicode = ""
                continue
            if self._escaped:
                self._escaped = False
                if char == "u":
                    self._unicode = "\\u"
                else:
                    output.append({"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(char, char))
                continue
            if char == "\\":
                self._escaped = True
            elif char == '"':
                self._finished = True
            else:
                output.append(char)
        return "".join(output)


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
        log.warning("LLM 响应 strip 后为空, raw_len=%d", len(raw))

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
            log.warning("JSON 中 reply 为空, response_len=%d", len(text))
            return text, _DEFAULT_INSTRUCT
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        log.warning("LLM 响应不是合法 JSON: %s, response_len=%d", e, len(text))
        return text, _DEFAULT_INSTRUCT


class AgentLoop:
    """Agent 主循环：Input → PreLLM → LLM → PostLLM → PostOutput"""

    def __init__(
        self,
        history_path: str = "",
        *,
        llm=None,
        pipeline=None,
        max_conversation_turns: int | None = None,
        max_regenerate: int | None = None,
        safety_policy=None,
    ):
        if llm is None or max_conversation_turns is None or max_regenerate is None:
            from ..config.settings import Settings
            settings = Settings.get()
        else:
            settings = None

        if llm is None:
            from ..llm.manager import get_llm_client
            llm = get_llm_client()
        self._llm = llm
        turns = max_conversation_turns if max_conversation_turns is not None else settings.max_conversation_turns
        self._messages = MessageManager(max_turns=turns)
        self._history_path = history_path
        self._max_regenerate = max_regenerate if max_regenerate is not None else settings.max_regenerate
        self._turn_lock = asyncio.Lock()
        if safety_policy is None:
            from ..services.safety import SafetyPolicy
            safety_policy = SafetyPolicy()
        self._safety_policy = safety_policy

        if history_path:
            loaded = self._messages.load_from_file(history_path)
            if loaded:
                log.info("对话历史已从磁盘恢复, 轮数=%d", self._messages.conversation_turns)

        self._pipeline = pipeline or Pipeline()
        if pipeline is None:
            self._pipeline.init_deps(self._messages)

    async def run(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        统一对话入口。
        返回: (reply_text, instruct_text)
        """
        ctx = await self.run_once(user_message)
        yield ctx.response
        yield ctx.instruct_text

    async def run_once(self, user_message: str) -> PipelineContext:
        """Process one complete turn and return its full typed context.

        A Soul owns one ordered conversation, so concurrent requests are
        serialized to prevent history and persistence from interleaving.
        """
        async with self._turn_lock:
            async for event in self._stream_unlocked(user_message):
                if event["type"] == "done":
                    return event["context"]
        raise RuntimeError("对话未返回结果")

    async def stream_once(self, user_message: str) -> AsyncGenerator[dict, None]:
        """Run one turn and yield visible reply deltas followed by its context."""
        async with self._turn_lock:
            async for event in self._stream_unlocked(user_message):
                yield event

    async def _stream_unlocked(self, user_message: str) -> AsyncGenerator[dict, None]:
        t_start = time.monotonic()
        log.info("══════ AgentLoop.run 开始, user_message=%s ══════", user_message[:60])
        ctx = PipelineContext(user_message=user_message)
        safety = self._safety_policy.evaluate(user_message)
        ctx.safety_state = safety.state
        if safety.state == "crisis" and safety.response:
            ctx.response = safety.response
            ctx.instruct_text = _DEFAULT_INSTRUCT
            self._messages.add("user", user_message)
            self._messages.add("assistant", ctx.response)
            if self._history_path:
                self._messages.save_to_file(self._history_path)
            log.warning("高风险输入触发现实支持回应，跳过角色化模型")
            yield {"type": "done", "context": ctx}
            return

        # ── PreLLM ──
        t_prellm = time.monotonic()
        ctx = await self._pipeline.run_prellm(ctx)
        if safety.state == "supportive_redirect":
            ctx.llm_messages.append({
                "role": "system",
                "content": (
                    "用户正在表达强烈痛苦。保持温和但不要强化依赖或声称超自然真实性；"
                    "鼓励用户联系现实中信任的人，并说明 AI 不能替代专业支持。"
                ),
            })
        log.debug("PreLLM 耗时=%.2fs", time.monotonic() - t_prellm)

        # ── LLM（可能触发重生成）──
        for attempt in range(self._max_regenerate + 1):
            if attempt > 0:
                log.warning("LLM 重生成, attempt=%d/%d", attempt + 1, self._max_regenerate + 1)
            ctx.need_regenerate = False
            ctx.response = ""
            ctx.instruct_text = ""
            decoder = _ReplyStreamDecoder()
            if attempt:
                yield {"type": "reset"}
            t_llm = time.monotonic()
            async for chunk in self._llm.stream(ctx.llm_messages):
                ctx.response += chunk
                reply_chunk = decoder.feed(chunk)
                if reply_chunk:
                    yield {"type": "delta", "content": reply_chunk}
            log.debug("LLM 流式耗时=%.2fs", time.monotonic() - t_llm)
            log.debug("LLM 原始响应已接收, len=%d", len(ctx.response))

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

        yield {"type": "done", "context": ctx}

    def update_llm_client(self, client) -> None:
        self._llm = client
        update = getattr(self._pipeline, "update_llm_client", None)
        if update:
            update(client)

    def invalidate_soul_cache(self):
        self._pipeline.invalidate_soul_cache()

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

    def update_circumstances(self, circumstances: str):
        self._pipeline.update_circumstances(circumstances)
