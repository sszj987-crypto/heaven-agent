from pathlib import Path


class VoiceUnavailable(RuntimeError):
    pass


class DisabledVoiceService:
    """Text-only fallback used when optional local voice packages are absent."""

    def __init__(self, data_dir: Path, reason: str = "语音组件未安装"):
        self._data_dir = Path(data_dir)
        self._reason = reason

    @property
    def has_reference(self) -> bool:
        return False

    @property
    def supports_instruction(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    def save_reference_audio(self, _audio_bytes: bytes) -> None:
        raise VoiceUnavailable(f"{self._reason}。请运行 scripts/bootstrap.py --voice")

    async def create_reference(
        self, _audio: bytes, _filename: str, _content_type: str
    ) -> bytes:
        raise VoiceUnavailable(self._reason)

    async def speak(self, _text: str, _config=None):
        raise VoiceUnavailable(self._reason)
        yield b""
