from unittest.mock import MagicMock
import pytest
from src.voice.asr import ASRService, MockASRService


class TestASRService:
    def setup_method(self):
        self._asr = ASRService()

    @pytest.mark.asyncio
    async def test_transcribe_returns_text(self):
        mock_result = {"text": "奶奶你好"}
        self._asr._transcribe_fn = MagicMock(return_value=mock_result)
        result = await self._asr.transcribe(b"fake audio data")
        assert result == "奶奶你好"

    @pytest.mark.asyncio
    async def test_transcribe_empty_response(self):
        mock_result = {"text": ""}
        self._asr._transcribe_fn = MagicMock(return_value=mock_result)
        result = await self._asr.transcribe(b"data")
        assert result == ""


class TestMockASRService:
    def setup_method(self):
        self._asr = MockASRService()

    @pytest.mark.asyncio
    async def test_returns_mock_text(self):
        result = await self._asr.transcribe(b"any data")
        assert "[mock" in result
