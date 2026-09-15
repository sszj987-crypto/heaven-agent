import json
import asyncio
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator
from .pipeline import Pipeline
from .context import PipelineContext
from .message import MessageManager
from .modules import prellm as _prellm
from .modules import postllm as _postllm
from .modules import postoutput as _postoutput
from ..config.logger import get_logger
from ..observability import current_request_id, get_agent_tracer, start_agent_span

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
    期望 JSON 格式：{"reply": "...", "instruct": "..."}。
    解析失败时整段文本作为 reply，使用默认语气。
    """
    text = raw.strip()

    if text:
        log.debug("LLM 响应已接收, stripped_len=%d", len(text))
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
            log.debug("已去除 markdown 代码块, stripped_len=%d", len(text))
        elif len(lines) > 1:
            # 只有开头 ``` 没有结尾 ```，尝试去掉第一行
            text = "\n".join(lines[1:]).strip()
            log.debug("已去除 markdown 代码块开头, stripped_len=%d", len(text))

    # 尝试解析 JSON
    try:
        data = json.loads(text)
        reply = str(data.get("reply", "")).strip()
        instruct = str(data.get("instruct", _DEFAULT_INSTRUCT)).strip()
        if reply:
            log.debug("JSON 解析成功: reply_len=%d, instruct_len=%d", len(reply), len(instruct))
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
        history_store=None,
        max_conversation_turns: int | None = None,
        max_regenerate: int | None = None,
        safety_policy=None,
        narrative_policy=None,
        tracer=None,
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
        self._history_store = history_store
        self._max_regenerate = max_regenerate if max_regenerate is not None else settings.max_regenerate
        self._turn_lock = asyncio.Lock()
        if safety_policy is None:
            from ..services.safety import SafetyPolicy
            safety_policy = SafetyPolicy()
        self._safety_policy = safety_policy
        if narrative_policy is None:
            from ..services.narrative import NarrativePolicy
            narrative_policy = NarrativePolicy()
        self._narrative_policy = narrative_policy
        self._tracer = tracer or get_agent_tracer()

        if history_store is not None:
            for message in history_store.load():
                self._messages.add(message["role"], message["content"])
            if self._messages.get_all():
                log.info(
                    "对话历史已从 SQLite 恢复, 轮数=%d",
                    self._messages.conversation_turns,
                )
        elif history_path:
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
        completed_context = None
        async with self._turn_lock:
            async for event in self._stream_unlocked(user_message):
                if event["type"] == "done":
                    completed_context = event["context"]
        if completed_context is None:
            raise RuntimeError("对话未返回结果")
        return completed_context

    async def stream_once(self, user_message: str) -> AsyncGenerator[dict, None]:
        """Run one turn and yield visible reply deltas followed by its context."""
        async with self._turn_lock:
            stream = self._stream_unlocked(user_message)
            try:
                async for event in stream:
                    yield event
            finally:
                await stream.aclose()

    async def _stream_unlocked(self, user_message: str) -> AsyncGenerator[dict, None]:
        attributes = {
            "gen_ai.operation.name": "invoke_agent",
            "heaven.agent.input_chars": len(user_message),
            "heaven.agent.history_turns": self._messages.conversation_turns,
        }
        request_id = current_request_id()
        turn_id = request_id or uuid.uuid4().hex[:16]
        if request_id:
            attributes["heaven.request.id"] = request_id
        attributes["heaven.agent.turn_id"] = turn_id

        turn_started = time.monotonic()
        outcome = "closed"
        log.debug(
            "agent_trace turn_id=%s stage=turn event=start input_chars=%d history_turns=%d",
            turn_id,
            len(user_message),
            self._messages.conversation_turns,
        )
        with start_agent_span(
            self._tracer,
            "heaven.agent.turn",
            attributes=attributes,
        ) as turn_span:
            turn = self._run_turn(user_message, turn_span, turn_id)
            try:
                async for event in turn:
                    yield event
                outcome = "completed"
            except Exception as exc:
                outcome = "error"
                log.debug(
                    "agent_trace turn_id=%s stage=turn event=error error_type=%s",
                    turn_id,
                    type(exc).__name__,
                )
                raise
            finally:
                await turn.aclose()
                log.debug(
                    "agent_trace turn_id=%s stage=turn event=end outcome=%s duration_ms=%.1f",
                    turn_id,
                    outcome,
                    (time.monotonic() - turn_started) * 1000,
                )

    async def _run_turn(
        self,
        user_message: str,
        turn_span,
        turn_id: str,
    ) -> AsyncGenerator[dict, None]:
        t_start = time.monotonic()
        log.info("══════ AgentLoop.run 开始, input_chars=%d ══════", len(user_message))
        ctx = PipelineContext(user_message=user_message)
        narrative = self._narrative_policy.evaluate(user_message)
        ctx.afterlife_topic_allowed = narrative.afterlife_topic_allowed
        turn_span.set_attribute(
            "heaven.narrative.afterlife_topic_allowed",
            narrative.afterlife_topic_allowed,
        )
        log.debug(
            "agent_trace turn_id=%s stage=narrative_policy afterlife_allowed=%s",
            turn_id,
            narrative.afterlife_topic_allowed,
        )
        stage_started = time.monotonic()
        with start_agent_span(
            self._tracer,
            "heaven.agent.safety",
            parent=turn_span,
        ) as safety_span:
            safety = self._safety_policy.evaluate(user_message)
            safety_span.set_attribute("heaven.safety.state", safety.state)
        log.debug(
            "agent_trace turn_id=%s stage=safety duration_ms=%.1f state=%s",
            turn_id,
            (time.monotonic() - stage_started) * 1000,
            safety.state,
        )
        ctx.safety_state = safety.state
        turn_span.set_attribute("heaven.safety.state", safety.state)
        if safety.state == "crisis" and safety.response:
            ctx.response = safety.response
            ctx.instruct_text = _DEFAULT_INSTRUCT
            with start_agent_span(
                self._tracer,
                "heaven.agent.history.persist",
                parent=turn_span,
            ) as history_span:
                self._record_history_turn(user_message, ctx.response)
                history_span.set_attribute(
                    "heaven.agent.history_turns", self._messages.conversation_turns
                )
            turn_span.set_attribute("heaven.agent.output_chars", len(ctx.response))
            turn_span.set_attribute("heaven.agent.regeneration_count", 0)
            log.debug(
                "agent_trace turn_id=%s stage=history_persist history_turns=%d",
                turn_id,
                self._messages.conversation_turns,
            )
            log.warning("高风险输入触发现实支持回应，跳过角色化模型")
            yield {"type": "done", "context": ctx}
            return

        # ── PreLLM ──
        t_prellm = time.monotonic()
        with start_agent_span(
            self._tracer,
            "heaven.agent.prellm",
            parent=turn_span,
        ) as prellm_span:
            ctx = await self._pipeline.run_prellm(ctx)
            prellm_span.set_attribute("heaven.agent.llm_message_count", len(ctx.llm_messages))
            prellm_span.set_attribute(
                "heaven.agent.retrieved_memory_count", len(ctx.retrieved_memories)
            )
            if ctx.context_budget:
                prellm_span.set_attribute(
                    "heaven.agent.context.input_chars",
                    ctx.context_budget.get("input_chars", 0),
                )
                prellm_span.set_attribute(
                    "heaven.agent.context.output_chars",
                    ctx.context_budget.get("output_chars", 0),
                )
                prellm_span.set_attribute(
                    "heaven.agent.context.dropped_history_messages",
                    ctx.context_budget.get("dropped_history_messages", 0),
                )
                prellm_span.set_attribute(
                    "heaven.agent.context.system_compacted",
                    ctx.context_budget.get("system_compacted", False),
                )
                prellm_span.set_attribute(
                    "heaven.agent.context.overflow_chars",
                    ctx.context_budget.get("overflow_chars", 0),
                )
        if safety.state == "supportive_redirect":
            supportive_message = {
                "role": "system",
                "content": (
                    "用户正在表达强烈痛苦。保持温和但不要强化依赖或声称超自然真实性；"
                    "鼓励用户联系现实中信任的人，并说明 AI 不能替代专业支持。"
                ),
            }
            # 保持本轮方言指令仍是离当前用户输入最近的 system message。
            insert_at = max(len(ctx.llm_messages) - 1, 0)
            if ctx.dialect_text_instruction and insert_at > 0:
                insert_at -= 1
            ctx.llm_messages.insert(insert_at, supportive_message)
        log.debug(
            "agent_trace turn_id=%s stage=prellm duration_ms=%.1f llm_messages=%d memories=%d",
            turn_id,
            (time.monotonic() - t_prellm) * 1000,
            len(ctx.llm_messages),
            len(ctx.retrieved_memories),
        )

        # ── LLM（可能触发重生成）──
        for attempt in range(self._max_regenerate + 1):
            if attempt > 0:
                log.warning("LLM 重生成, attempt=%d/%d", attempt + 1, self._max_regenerate + 1)
            ctx.need_regenerate = False
            ctx.output_policy_violation = ""
            ctx.response = ""
            ctx.instruct_text = ""
            decoder = _ReplyStreamDecoder()
            decoded_reply = ""
            suppress_visible_reply = False
            if attempt:
                yield {"type": "reset"}
            t_llm = time.monotonic()
            model_name = getattr(self._llm, "model", None)
            generation_attributes = {
                "gen_ai.operation.name": "chat",
                "heaven.agent.generation_attempt": attempt + 1,
                "heaven.agent.llm_message_count": len(ctx.llm_messages),
            }
            if isinstance(model_name, str) and model_name:
                generation_attributes["gen_ai.request.model"] = model_name
            with start_agent_span(
                self._tracer,
                "heaven.agent.llm.generate",
                parent=turn_span,
                attributes=generation_attributes,
            ) as generation_span:
                async for chunk in self._llm.stream(ctx.llm_messages):
                    ctx.response += chunk
                    reply_chunk = decoder.feed(chunk)
                    if reply_chunk:
                        decoded_reply += reply_chunk
                        streaming_violation = self._narrative_policy.output_violation(
                            decoded_reply,
                            afterlife_topic_allowed=ctx.afterlife_topic_allowed,
                        )
                        if streaming_violation:
                            suppress_visible_reply = True
                            generation_span.set_attribute(
                                "heaven.narrative.streaming_output_suppressed", True
                            )
                        if not suppress_visible_reply:
                            yield {"type": "delta", "content": reply_chunk}
                generation_span.set_attribute(
                    "heaven.agent.raw_output_chars", len(ctx.response)
                )
            log.debug(
                "agent_trace turn_id=%s stage=llm_generate duration_ms=%.1f attempt=%d raw_output_chars=%d model=%s",
                turn_id,
                (time.monotonic() - t_llm) * 1000,
                attempt + 1,
                len(ctx.response),
                model_name or "unknown",
            )

            # 解析 LLM 响应：分离回复文本和语音语气
            with start_agent_span(
                self._tracer,
                "heaven.agent.output.parse",
                parent=turn_span,
            ) as parse_span:
                reply, instruct = _parse_llm_response(ctx.response)
                ctx.response = reply
                ctx.instruct_text = instruct
                parse_span.set_attribute("heaven.agent.output_chars", len(reply))
                parse_span.set_attribute("heaven.agent.instruct_chars", len(instruct))
            log.debug(
                "agent_trace turn_id=%s stage=output_parse output_chars=%d instruct_chars=%d",
                turn_id,
                len(reply),
                len(instruct),
            )

            stage_started = time.monotonic()
            with start_agent_span(
                self._tracer,
                "heaven.agent.postllm",
                parent=turn_span,
            ) as postllm_span:
                ctx = await self._pipeline.run_postllm(ctx)
                postllm_span.set_attribute(
                    "heaven.agent.needs_regeneration", ctx.need_regenerate
                )
            log.debug(
                "agent_trace turn_id=%s stage=postllm duration_ms=%.1f regenerate=%s",
                turn_id,
                (time.monotonic() - stage_started) * 1000,
                ctx.need_regenerate,
            )

            if not ctx.need_regenerate:
                break

        if ctx.output_policy_violation:
            ctx.response = self._narrative_policy.safe_fallback
            ctx.instruct_text = _DEFAULT_INSTRUCT
            ctx.need_regenerate = False
            turn_span.set_attribute("heaven.narrative.fallback_used", True)
            log.warning(
                "输出在重试上限内仍未通过敏感叙事检查，已使用安全兜底, violation=%s",
                ctx.output_policy_violation,
            )
            yield {"type": "reset"}
            yield {"type": "delta", "content": ctx.response}

        # ── 记录对话历史 ──
        stage_started = time.monotonic()
        with start_agent_span(
            self._tracer,
            "heaven.agent.history.persist",
            parent=turn_span,
        ) as history_span:
            self._record_history_turn(user_message, ctx.response)
            history_span.set_attribute(
                "heaven.agent.history_turns", self._messages.conversation_turns
            )
            history_span.set_attribute(
                "heaven.agent.history_message_count", len(self._messages.get_all())
            )
        log.debug("对话历史更新, 轮数=%d, 总消息=%d, 对话字符=%d",
                  self._messages.conversation_turns, len(self._messages.get_all()),
                  self._messages.conversation_chars)
        log.debug(
            "agent_trace turn_id=%s stage=history_persist duration_ms=%.1f history_turns=%d history_messages=%d",
            turn_id,
            (time.monotonic() - stage_started) * 1000,
            self._messages.conversation_turns,
            len(self._messages.get_all()),
        )

        # ── PostOutput ──
        stage_started = time.monotonic()
        with start_agent_span(
            self._tracer,
            "heaven.agent.postoutput",
            parent=turn_span,
        ) as postoutput_span:
            ctx = await self._pipeline.run_postoutput(ctx)
            postoutput_span.set_attribute("heaven.agent.output_chars", len(ctx.response))
        log.debug(
            "agent_trace turn_id=%s stage=postoutput duration_ms=%.1f output_chars=%d",
            turn_id,
            (time.monotonic() - stage_started) * 1000,
            len(ctx.response),
        )

        total_elapsed = time.monotonic() - t_start
        turn_span.set_attribute("heaven.agent.output_chars", len(ctx.response))
        turn_span.set_attribute("heaven.agent.regeneration_count", attempt)
        turn_span.set_attribute("heaven.agent.duration_ms", total_elapsed * 1000)
        log.info("══════ AgentLoop.run 完成, 总耗时=%.2fs, reply_len=%d, instruct_len=%d, turns=%d ══════",
                 total_elapsed, len(ctx.response), len(ctx.instruct_text), self._messages.conversation_turns)

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
        """清空内存和持久化的活动对话历史。"""
        self._messages.clear()
        if self._history_store is not None:
            self._history_store.clear()
        if self._history_path:
            p = Path(self._history_path)
            if p.exists():
                p.unlink()
                log.info("对话历史文件已删除: %s", p)

    def _persist_history(self) -> None:
        if self._history_store is not None:
            self._history_store.replace(self._messages.get_all())
        elif self._history_path:
            self._messages.save_to_file(self._history_path)

    def _record_history_turn(self, user_message: str, response: str) -> None:
        """Keep memory and durable history aligned when persistence fails."""
        previous = self._messages.get_all()
        self._messages.add("user", user_message)
        self._messages.add("assistant", response)
        try:
            self._persist_history()
        except Exception:
            self._messages.clear()
            for message in previous:
                self._messages.add(message["role"], message["content"])
            log.error("对话持久化失败，已回滚本轮内存历史")
            raise

    def update_circumstances(self, circumstances: str):
        self._pipeline.update_circumstances(circumstances)
