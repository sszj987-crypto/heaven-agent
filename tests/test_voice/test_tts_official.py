"""官方 CosyVoice TTS 后端测试"""

import tempfile
from pathlib import Path

import numpy as np
import pytest


class TestOfficialTTSService:
    """测试 OfficialTTSService 基本接口"""

    def test_init_creates_data_dir(self):
        from src.voice.tts_official import OfficialTTSService

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "voice"
            svc = OfficialTTSService(data_dir)
            assert data_dir.exists()
            assert svc.has_reference is False

    def test_has_reference_without_audio(self):
        from src.voice.tts_official import OfficialTTSService

        with tempfile.TemporaryDirectory() as tmp:
            svc = OfficialTTSService(Path(tmp))
            assert svc.has_reference is False

    def test_save_reference_audio(self):
        from src.voice.tts_official import OfficialTTSService

        with tempfile.TemporaryDirectory() as tmp:
            svc = OfficialTTSService(Path(tmp))
            # 生成一段简单的 24kHz 正弦波作为参考音频
            sr = 24000
            duration = 5.0
            t = np.linspace(0, duration, int(sr * duration), endpoint=False)
            audio = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)

            import io
            import wave
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes((audio * 32767).astype(np.int16).tobytes())
            buf.seek(0)

            svc.save_reference_audio(buf.read())
            assert svc.has_reference is True
            assert svc._ref_audio_path.exists()

    def test_speak_without_reference_returns_empty(self):
        from src.voice.tts_official import OfficialTTSService

        with tempfile.TemporaryDirectory() as tmp:
            svc = OfficialTTSService(Path(tmp))
            import asyncio

            async def _run():
                chunks = []
                async for chunk in svc.speak("你好"):
                    chunks.append(chunk)
                return chunks

            chunks = asyncio.run(_run())
            assert len(chunks) == 1
            assert chunks[0] == b""
