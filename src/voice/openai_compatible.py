"""OpenAI-format Text-to-Speech adapter for OpenAI and compatible gateways."""

from __future__ import annotations

from typing import AsyncGenerator
from urllib.parse import urlparse

import httpx

from ..agent.context import TTSConfig
from ..config.loader import OpenAICompatibleTTSConfig
from .audio import validate_wav_structure
from .service import VoiceCapabilities, VoiceUnavailable


class OpenAICompatibleTTSError(Exception):
    """Safe failure message for an OpenAI-compatible TTS provider."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class OpenAICompatibleTTSClient:
    _TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OpenAI 兼容语音接口地址必须是有效的 HTTP(S) URL")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = client or httpx.AsyncClient(timeout=self._TIMEOUT)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def test_connection(self) -> bool:
        """Check the common OpenAI discovery endpoint without synthesizing audio."""
        try:
            response = await self._http.get(
                f"{self._base_url}/models",
                headers=self._headers(),
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def synthesize(
        self, text: str, model: str, voice: str, instructions: str
    ) -> bytes:
        payload: dict[str, str] = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "wav",
        }
        # OpenAI documents that the legacy models reject/ignore instructions.
        if instructions.strip() and model not in {"tts-1", "tts-1-hd"}:
            payload["instructions"] = instructions
        try:
            response = await self._http.post(
                f"{self._base_url}/audio/speech",
                headers=self._headers(),
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise OpenAICompatibleTTSError(
                "无法连接 OpenAI 兼容语音服务", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenAICompatibleTTSError(
                "无法连接 OpenAI 兼容语音服务", retryable=True
            ) from exc

        if response.status_code in (401, 403):
            raise OpenAICompatibleTTSError("OpenAI 兼容语音 API Key 无效或无权限")
        if response.status_code == 429:
            raise OpenAICompatibleTTSError(
                "OpenAI 兼容语音请求频率或额度受限", retryable=True
            )
        if response.status_code >= 400:
            raise OpenAICompatibleTTSError(
                "OpenAI 兼容语音服务调用失败",
                retryable=response.status_code >= 500,
            )
        try:
            validate_wav_structure(response.content)
        except ValueError as exc:
            raise OpenAICompatibleTTSError(
                "OpenAI 兼容语音服务返回的音频无效", retryable=True
            ) from exc
        return response.content

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}


class OpenAICompatibleTTSService:
    """One configurable, no-cloning TTS voice for an OpenAI-format endpoint."""

    capabilities = VoiceCapabilities(
        requires_reference=False,
        supports_voice_cloning=False,
        supports_instruction=True,
    )

    def __init__(
        self,
        config: OpenAICompatibleTTSConfig,
        client: OpenAICompatibleTTSClient | None = None,
    ):
        self._config = config
        self._client = client or OpenAICompatibleTTSClient(
            config.base_url, config.api_key
        )

    @property
    def has_reference(self) -> bool:
        return False

    @property
    def is_ready(self) -> bool:
        return bool(
            self._config.base_url.strip()
            and self._config.api_key.strip()
            and self._config.model.strip()
            and self._config.voice.strip()
        )

    @property
    def supports_instruction(self) -> bool:
        return self.capabilities.supports_instruction

    async def aclose(self) -> None:
        await self._client.aclose()

    async def speak(
        self, text: str, config: TTSConfig | None = None
    ) -> AsyncGenerator[bytes, None]:
        if not self.is_ready:
            raise VoiceUnavailable("请先在设置中配置 OpenAI 兼容语音服务")
        instructions = config.instruct_text if config is not None else ""
        yield await self._client.synthesize(
            text,
            self._config.model,
            self._config.voice,
            instructions,
        )
