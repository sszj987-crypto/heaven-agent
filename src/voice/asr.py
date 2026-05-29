import tempfile
import asyncio
import traceback
from pathlib import Path
from ..config.logger import get_logger

log = get_logger("asr")


class ASRService:
    """本地语音识别服务，基于 mlx-whisper"""

    def __init__(self, model: str = "mlx-community/whisper-small-mlx"):
        self._model = model

    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        将音频 bytes 转为文字。
        在线程池中运行 mlx-whisper 推理，避免阻塞事件循环。
        """
        log.debug("ASR 转写开始, audio size=%d bytes, model=%s", len(audio_bytes), self._model)
        try:
            result = await asyncio.to_thread(self._transcribe_sync, audio_bytes)
            log.debug("ASR 转写完成: %s...", result[:50])
            return result
        except Exception as e:
            log.error("ASR 转写失败: %s\n%s", e, traceback.format_exc())
            raise

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        import mlx_whisper

        # 写入临时文件（mlx-whisper 接受文件路径）
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            result = mlx_whisper.transcribe(tmp_path, path_or_hf_repo=self._model)
            return result.get("text", "").strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class MockASRService:
    """Mock ASR 用于测试（无 MLX 时使用）"""

    async def transcribe(self, audio_bytes: bytes) -> str:
        return "[mock speech-to-text output]"
