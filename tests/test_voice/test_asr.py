import pytest
from unittest.mock import MagicMock, patch
from src.voice.asr import ASRService, MockASRService


class TestASRService:
    def setup_method(self):
        self._asr = ASRService("http://localhost:8080")

    @pytest.mark.asyncio
    async def test_transcribe_sends_audio(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"text": "奶奶你好"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            result = await self._asr.transcribe(b"fake audio data")

        assert result == "奶奶你好"
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_empty_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await self._asr.transcribe(b"data")

        assert result == ""


class TestMockASRService:
    def setup_method(self):
        self._asr = MockASRService()

    @pytest.mark.asyncio
    async def test_returns_mock_text(self):
        result = await self._asr.transcribe(b"any data")
        assert "[mock" in result
