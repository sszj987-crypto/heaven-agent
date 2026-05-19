import io
import httpx
import wave


class ASRService:
    """Fish Speech STT 语音识别服务"""

    def __init__(self, fish_speech_url: str):
        self._url = fish_speech_url.rstrip("/")

    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        将音频 bytes 转为文字。
        调用 Fish Speech ASR API。
        """
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._url}/v1/asr",
                files={"audio": ("audio.wav", audio_bytes, "audio/wav")},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("text", "")


class MockASRService:
    """Mock ASR 用于测试（无 Fish Speech 时使用）"""

    async def transcribe(self, audio_bytes: bytes) -> str:
        return "[mock speech-to-text output]"
