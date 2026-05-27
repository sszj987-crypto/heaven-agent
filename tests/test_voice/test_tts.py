import tempfile
from pathlib import Path
import pytest
from src.agent.context import TTSConfig
from src.voice.tts import TTSService, MockTTSService


class TestTTSService:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._data_dir = Path(self._tmp.name)
        self._tts = TTSService(self._data_dir)

    def teardown_method(self):
        self._tmp.cleanup()

    def test_has_reference_false_initially(self):
        assert not self._tts.has_reference

    def test_save_reference_audio(self):
        self._tts.save_reference_audio(b"fake audio data")
        assert self._tts.has_reference
        assert self._tts._ref_audio_path.exists()

    @pytest.mark.asyncio
    async def test_speak_without_reference_returns_empty(self):
        chunks = []
        async for chunk in self._tts.speak("你好"):
            chunks.append(chunk)
        assert chunks == [b""]


class TestMockTTSService:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tts = MockTTSService(Path(self._tmp.name))

    def teardown_method(self):
        self._tmp.cleanup()

    def test_save_reference_audio(self):
        self._tts.save_reference_audio(b"test")
        assert self._tts.has_reference

    @pytest.mark.asyncio
    async def test_returns_empty_bytes(self):
        chunks = []
        async for chunk in self._tts.speak("any text"):
            chunks.append(chunk)
        assert chunks == [b""]
