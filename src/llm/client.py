import json
import time
import httpx
from typing import AsyncGenerator
from ..config.logger import get_logger

log = get_logger("llm")


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
                 temperature: float | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._temperature = temperature
        self._http = httpx.AsyncClient(timeout=timeout)
        log.info("LLMClient 初始化, base_url=%s, model=%s, timeout=%ds",
                 self._base_url, self._model, self._timeout)

    @property
    def model(self) -> str:
        return self._model

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
            body = {
                "model": self._model,
                "messages": messages,
            }
            if max_tokens is not None:
                body["max_tokens"] = max_tokens
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            if self._temperature is not None:
                body["temperature"] = self._temperature
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
        total_tokens = 0
        input_chars = sum(len(m["content"]) for m in messages)
        log.info("LLM stream 开始, model=%s, messages=%d, input_chars=%d, max_tokens=%s, json_mode=%s",
                 self._model, len(messages), input_chars, max_tokens or "default", json_mode)
        _log_messages_debug(messages)
        t0 = time.monotonic()
        try:
            body = {
                "model": self._model,
                "messages": messages,
                "stream": True,
            }
            if max_tokens is not None:
                body["max_tokens"] = max_tokens
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            if self._temperature is not None:
                body["temperature"] = self._temperature
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
                log.debug("LLM stream 连接成功, status=%d", response.status_code)
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line.removeprefix("data: ")
                        if data_str == "[DONE]":
                            elapsed = time.monotonic() - t0
                            log.info("LLM stream 完成, 耗时=%.2fs, total_tokens=%d, tokens/s=%.1f",
                                     elapsed, total_tokens, total_tokens / elapsed if elapsed > 0 else 0)
                            return
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                total_tokens += 1
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as e:
            elapsed = time.monotonic() - t0
            log.error("LLM stream 失败, 耗时=%.2fs, error=%s", elapsed, e)
            raise
