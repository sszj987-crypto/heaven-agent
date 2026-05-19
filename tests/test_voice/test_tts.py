import pytest
from unittest.mock import patch
from src.agent.context import TTSConfig
from src.voice.tts import TTSService, MockTTSService


class _FakeTTSResponse:
    """模拟 httpx stream 响应，避免 MagicMock 异步上下文管理器告警"""
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    def raise_for_status(self):
        pass


class TestTTSService:
    def setup_method(self):
        self._tts = TTSService("http://localhost:8080")

    @pytest.mark.asyncio
    async def test_speak_sends_request(self):
        fake = _FakeTTSResponse([b"audio_chunk1", b"audio_chunk2"])

        with patch("httpx.AsyncClient.stream", return_value=fake):
            chunks = []
            async for chunk in self._tts.speak("你好"):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0] == b"audio_chunk1"

    @pytest.mark.asyncio
    async def test_speak_with_custom_config(self):
        config = TTSConfig(emotion="gentle", speed=0.85, pitch=-2, pause_ms=500)
        fake = _FakeTTSResponse([b"audio"])

        with patch("httpx.AsyncClient.stream", return_value=fake):
            chunks = []
            async for chunk in self._tts.speak("你好", config):
                chunks.append(chunk)

        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_speak_default_config_when_none(self):
        fake = _FakeTTSResponse([b"data"])

        with patch("httpx.AsyncClient.stream", return_value=fake):
            chunks = []
            async for chunk in self._tts.speak("test", None):
                chunks.append(chunk)

        assert len(chunks) == 1


class TestMockTTSService:
    def setup_method(self):
        self._tts = MockTTSService()

    @pytest.mark.asyncio
    async def test_returns_empty_bytes(self):
        chunks = []
        async for chunk in self._tts.speak("any text"):
            chunks.append(chunk)
        assert chunks == [b""]
