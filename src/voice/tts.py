import httpx
from typing import AsyncGenerator
from ..agent.context import TTSConfig


class TTSService:
    """Fish Speech TTS 语音合成服务"""

    def __init__(self, fish_speech_url: str):
        self._url = fish_speech_url.rstrip("/")

    async def speak(self, text: str, config: TTSConfig | None = None) -> AsyncGenerator[bytes, None]:
        """
        将文字转为语音，流式产出音频 bytes。
        config 包含 emotion / speed / pitch / pause_ms 精细参数。
        """
        cfg = config or TTSConfig()
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{self._url}/v1/tts",
                json={
                    "text": text,
                    "emotion": cfg.emotion,
                    "speed": cfg.speed,
                    "pitch": cfg.pitch,
                    "pause_duration": cfg.pause_ms,
                    "speaker": cfg.speaker,
                },
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk

    async def create_voice(self, name: str, audio_bytes: bytes) -> str:
        """
        上传参考音频创建声纹克隆，返回 speaker_id。
        调用 Fish Speech POST /v1/voice，multipart 上传 name + audio。
        """
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._url}/v1/voice",
                data={"name": name},
                files={"audio": ("reference.wav", audio_bytes, "audio/wav")},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("id", "")


class MockTTSService:
    """Mock TTS 用于测试（无 Fish Speech 时使用）"""

    async def speak(self, text: str, config: TTSConfig | None = None) -> AsyncGenerator[bytes, None]:
        yield b""

    async def create_voice(self, name: str, audio_bytes: bytes) -> str:
        return f"mock_speaker_{name}"
