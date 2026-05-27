import json
import httpx
from typing import AsyncGenerator
from ..config.logger import get_logger

log = get_logger("llm")


class LLMClient:
    """OpenAI 兼容接口的 LLM 客户端，支持所有 OpenAI 兼容的 Provider"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        log.debug("LLMClient 创建, base_url=%s, model=%s", self._base_url, self._model)

    @property
    def model(self) -> str:
        return self._model

    async def chat(self, messages: list[dict]) -> str:
        """非流式聊天，一次性返回完整回复"""
        url = f"{self._base_url}/chat/completions"
        log.debug("LLM chat 请求, url=%s, messages 数量=%d", url, len(messages))
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
                log.debug("LLM chat 成功, 响应长度=%d", len(content))
                return content
        except Exception as e:
            log.error("LLM chat 失败: %s", e)
            raise

    async def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """流式聊天，逐 token 产出回复"""
        url = f"{self._base_url}/chat/completions"
        total_tokens = 0
        log.debug("LLM stream 请求, url=%s, model=%s, messages 数量=%d",
                  url, self._model, len(messages))
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
                                log.debug("LLM stream 完成, 总 tokens=%d", total_tokens)
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
            log.error("LLM stream 失败: %s", e)
            raise
