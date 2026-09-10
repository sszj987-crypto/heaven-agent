import io
import json
import wave

import httpx
import pytest

from src.agent.context import TTSConfig
from src.config.loader import OpenAICompatibleTTSConfig
from src.voice.openai_compatible import (
    OpenAICompatibleTTSClient,
    OpenAICompatibleTTSError,
    OpenAICompatibleTTSService,
)


def valid_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24_000)
        wav_file.writeframes(b"\x00\x00" * 20)
    return output.getvalue()


def make_client(handler) -> OpenAICompatibleTTSClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleTTSClient("https://gateway.example/v1", "test-key", client=http)


async def test_synthesize_uses_openai_speech_contract():
    async def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/v1/audio/speech"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "gpt-4o-mini-tts",
            "input": "你好",
            "voice": "alloy",
            "response_format": "wav",
            "instructions": "温柔地说",
        }
        return httpx.Response(200, content=valid_wav())

    client = make_client(handler)
    try:
        assert await client.synthesize("你好", "gpt-4o-mini-tts", "alloy", "温柔地说") == valid_wav()
    finally:
        await client.aclose()


async def test_legacy_tts_model_omits_instructions():
    async def handler(request):
        assert "instructions" not in json.loads(request.content)
        return httpx.Response(200, content=valid_wav())

    client = make_client(handler)
    try:
        await client.synthesize("你好", "tts-1", "alloy", "温柔地说")
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("status", "message", "retryable"),
    [
        (401, "OpenAI 兼容语音 API Key 无效或无权限", False),
        (429, "OpenAI 兼容语音请求频率或额度受限", True),
        (500, "OpenAI 兼容语音服务调用失败", True),
    ],
)
async def test_synthesize_maps_provider_errors_safely(status, message, retryable):
    client = make_client(lambda _request: httpx.Response(status, text="private detail"))
    try:
        with pytest.raises(OpenAICompatibleTTSError, match=message) as error:
            await client.synthesize("你好", "gpt-4o-mini-tts", "alloy", "")
        assert error.value.retryable is retryable
    finally:
        await client.aclose()


async def test_service_is_ready_without_reference_and_yields_wav():
    class Client:
        async def synthesize(self, text, model, voice, instructions):
            assert (text, model, voice, instructions) == ("你好", "custom-tts", "voice_123", "平静地说")
            return valid_wav()

        async def aclose(self):
            pass

    service = OpenAICompatibleTTSService(
        OpenAICompatibleTTSConfig(api_key="key", model="custom-tts", voice="voice_123"),
        client=Client(),
    )

    assert service.has_reference is False
    assert service.is_ready is True
    assert service.capabilities.supports_voice_cloning is False
    assert [chunk async for chunk in service.speak("你好", TTSConfig(instruct_text="平静地说"))] == [valid_wav()]


async def test_connection_uses_models_without_synthesizing_audio():
    async def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": []})

    client = make_client(handler)
    try:
        assert await client.test_connection() is True
    finally:
        await client.aclose()
