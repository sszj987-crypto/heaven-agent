import json
import time
import httpx
from typing import AsyncGenerator
from ..config.logger import get_logger

log = get_logger("llm")


def _log_messages_debug(messages: list[dict]):
    """DEBUG 级别打印完整的 messages 全文（system prompt + history + current）"""
    if not log.isEnabledFor(10):  # DEBUG level
        return
    for i, msg in enumerate(messages):
        role = msg["role"]
        content = msg["content"]
        log.debug("[msg %d/%d] role=%s, len=%d\n%s", i + 1, len(messages), role, len(content), content)


class LLMClient:
    """OpenAI 兼容接口的 LLM 客户端，支持所有 OpenAI 兼容的 Provider"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        log.info("LLMClient 初始化, base_url=%s, model=%s", self._base_url, self._model)

    @property
    def model(self) -> str:
        return self._model

    async def chat(self, messages: list[dict]) -> str:
        """非流式聊天，一次性返回完整回复"""
        url = f"{self._base_url}/chat/completions"
        input_chars = sum(len(m["content"]) for m in messages)
        log.info("LLM chat 开始, url=%s, model=%s, messages=%d, input_chars=%d",
                 url, self._model, len(messages), input_chars)
        _log_messages_debug(messages)
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": messages,
                    },
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
                log.debug("LLM chat 响应全文:\n%s", content)
                return content
        except Exception as e:
            elapsed = time.monotonic() - t0
            log.error("LLM chat 失败, 耗时=%.2fs, error=%s", elapsed, e)
            raise

    async def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """流式聊天，逐 token 产出回复"""
        url = f"{self._base_url}/chat/completions"
        total_tokens = 0
        input_chars = sum(len(m["content"]) for m in messages)
        log.info("LLM stream 开始, model=%s, messages=%d, input_chars=%d",
                 self._model, len(messages), input_chars)
        _log_messages_debug(messages)
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": messages,
                        "stream": True,
                    },
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
