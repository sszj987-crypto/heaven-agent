import json
import time
import httpx
from typing import Any, AsyncGenerator
from ..config.logger import get_logger

log = get_logger("llm")


class LLMEmptyResponseError(RuntimeError):
    """The provider completed a request but sent no user-visible content."""


def _stream_payload(line: str) -> dict[str, Any] | str | None:
    """Decode standard SSE plus the newline-delimited JSON used by some gateways."""
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if line.startswith("data:"):
        line = line[len("data:"):].lstrip()
    if line == "[DONE]":
        return "[DONE]"
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _content_from_stream_chunk(chunk: dict[str, Any]) -> tuple[str, bool]:
    """Return visible text and whether a reasoning-only field was present."""
    choices = chunk.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
        candidates = (choice.get("delta"), choice.get("message"), choice)
    else:
        candidates = (chunk.get("message"), chunk)

    has_reasoning = False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        has_reasoning = has_reasoning or bool(
            candidate.get("reasoning_content") or candidate.get("reasoning")
        )
        content = candidate.get("content")
        if isinstance(content, str) and content:
            return content, has_reasoning
        if isinstance(content, list):
            text = "".join(
                item.get("text", "") for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            )
            if text:
                return text, has_reasoning
    return "", has_reasoning


def _log_messages_debug(messages: list[dict]):
    """DEBUG 级别只打印消息结构，不记录私密正文。"""
    if not log.isEnabledFor(10):  # DEBUG level
        return
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        log.debug("[msg %d/%d] role=%s, len=%d", i + 1, len(messages), role, len(content))


class LLMClient:
    """OpenAI 兼容接口的 LLM 客户端，支持所有 OpenAI 兼容的 Provider"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120,
                 temperature: float | None = None,
                 reasoning_effort: str | None = None,
                 include_stream_usage: bool = False):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._include_stream_usage = include_stream_usage
        self._http = httpx.AsyncClient(timeout=timeout)
        log.info("LLMClient 初始化, base_url=%s, model=%s, timeout=%ds",
                 self._base_url, self._model, self._timeout)

    @property
    def model(self) -> str:
        return self._model

    def _request_body(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self._model, "messages": messages}
        if stream:
            body["stream"] = True
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._reasoning_effort is not None:
            body["reasoning_effort"] = self._reasoning_effort
        if stream and self._include_stream_usage:
            body["stream_options"] = {"include_usage": True}
        return body

    async def aclose(self) -> None:
        await self._http.aclose()

    async def chat(self, messages: list[dict], timeout: float | None = None,
                   max_tokens: int | None = None, json_mode: bool = False) -> str:
        """非流式聊天，一次性返回完整回复。timeout/max_tokens/json_mode 可选覆盖默认值。"""
        url = f"{self._base_url}/chat/completions"
        input_chars = sum(len(m["content"]) for m in messages)
        effective_timeout = timeout if timeout is not None else self._timeout
        log.info("LLM chat 开始, url=%s, model=%s, messages=%d, input_chars=%d, timeout=%ds, max_tokens=%s, json_mode=%s",
                 url, self._model, len(messages), input_chars, effective_timeout,
                 max_tokens or "default", json_mode)
        _log_messages_debug(messages)
        t0 = time.monotonic()
        try:
            body = self._request_body(
                messages, max_tokens=max_tokens, json_mode=json_mode
            )
            response = await self._http.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=effective_timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            elapsed = time.monotonic() - t0
            usage = data.get("usage", {})
            log.info("LLM chat 完成, 耗时=%.2fs, reply_len=%d, prompt_tokens=%s, completion_tokens=%s",
                     elapsed, len(content),
                     usage.get("prompt_tokens", "N/A"),
                     usage.get("completion_tokens", "N/A"))
            log.debug("LLM chat 响应已接收, len=%d", len(content))
            if not content or len(content.strip()) == 0:
                log.warning("LLM chat 返回空内容, finish_reason=%s",
                          data["choices"][0].get("finish_reason", "N/A"))
            return content
        except Exception as e:
            elapsed = time.monotonic() - t0
            log.error("LLM chat 失败, 耗时=%.2fs, error_type=%s, error=%s",
                      elapsed, type(e).__name__, e)
            raise

    async def stream(self, messages: list[dict], max_tokens: int | None = None,
                     json_mode: bool = False) -> AsyncGenerator[str, None]:
        """流式聊天，逐 token 产出回复"""
        url = f"{self._base_url}/chat/completions"
        content_chunks = 0
        content_chars = 0
        input_chars = sum(len(m["content"]) for m in messages)
        log.info("LLM stream 开始, model=%s, messages=%d, input_chars=%d, max_tokens=%s, json_mode=%s",
                 self._model, len(messages), input_chars, max_tokens or "default", json_mode)
        _log_messages_debug(messages)
        t0 = time.monotonic()
        try:
            body = self._request_body(
                messages, stream=True, max_tokens=max_tokens, json_mode=json_mode
            )
            async with self._http.stream(
                "POST",
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            ) as response:
                response.raise_for_status()
                log.debug(
                    "LLM stream 响应头已收到, status=%d, elapsed=%.2fs",
                    response.status_code, time.monotonic() - t0,
                )
                payload_count = 0
                reasoning_chunks = 0
                first_content_elapsed: float | None = None
                usage: dict[str, Any] = {}
                async for line in response.aiter_lines():
                    payload = _stream_payload(line)
                    if payload is None:
                        continue
                    if payload == "[DONE]":
                        break
                    payload_count += 1
                    if isinstance(payload.get("usage"), dict):
                        usage = payload["usage"]
                    content, has_reasoning = _content_from_stream_chunk(payload)
                    reasoning_chunks += int(has_reasoning)
                    if content:
                        if first_content_elapsed is None:
                            first_content_elapsed = time.monotonic() - t0
                            log.info("LLM stream 首个内容, TTFT=%.2fs", first_content_elapsed)
                        content_chunks += 1
                        content_chars += len(content)
                        yield content
                elapsed = time.monotonic() - t0
                decode_elapsed = elapsed - first_content_elapsed if first_content_elapsed else 0
                log.info(
                    "LLM stream 完成, 耗时=%.2fs, TTFT=%s, content_chunks=%d, "
                    "content_chars=%d, decode_chunks/s=%.1f",
                    elapsed,
                    f"{first_content_elapsed:.2f}s" if first_content_elapsed is not None else "N/A",
                    content_chunks,
                    content_chars,
                    content_chunks / decode_elapsed if decode_elapsed > 0 else 0,
                )
                if usage:
                    prompt_tokens = usage.get("prompt_tokens")
                    prefill_tokens_per_s = (
                        prompt_tokens / first_content_elapsed
                        if isinstance(prompt_tokens, (int, float))
                        and first_content_elapsed is not None
                        and first_content_elapsed > 0
                        else None
                    )
                    log.info(
                        "LLM stream usage, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s, "
                        "prefill_tokens/s=%s",
                        prompt_tokens if prompt_tokens is not None else "N/A",
                        usage.get("completion_tokens", "N/A"),
                        usage.get("total_tokens", "N/A"),
                        f"{prefill_tokens_per_s:.1f}" if prefill_tokens_per_s is not None else "N/A",
                    )
                if content_chunks == 0:
                    if reasoning_chunks:
                        raise LLMEmptyResponseError(
                            "LLM 仅返回推理内容，未返回可展示回复；"
                            "请关闭模型思考模式或升级 Ollama。"
                        )
                    raise LLMEmptyResponseError(
                        f"LLM 流未包含可展示文本（已收到 {payload_count} 个数据块）。"
                    )
        except Exception as e:
            elapsed = time.monotonic() - t0
            log.error("LLM stream 失败, 耗时=%.2fs, error=%s", elapsed, e)
            raise
