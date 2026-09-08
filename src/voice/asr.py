import sys
import tempfile
import asyncio
import traceback
from pathlib import Path
from ..config.logger import get_logger

log = get_logger("asr")


class ASRService:
    """本地语音识别服务，基于 mlx-whisper"""

    def __init__(self, model: str = "mlx-community/whisper-small-mlx", transcribe_fn=None):
        self._model = model
        self._transcribe_fn = transcribe_fn

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
        if self._transcribe_fn is None:
            import mlx_whisper
            transcribe = mlx_whisper.transcribe
        else:
            transcribe = self._transcribe_fn

        # 写入临时文件（mlx-whisper 接受文件路径）
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            result = transcribe(tmp_path, path_or_hf_repo=self._model)
            return result.get("text", "").strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class FasterWhisperASRService:
    """跨平台 ASR，基于 faster-whisper (CTranslate2)，CPU int8 推理"""

    def __init__(self, model_size: str = "small"):
        self._model_size = model_size
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel
        self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        return self._model

    async def transcribe(self, audio_bytes: bytes) -> str:
        log.debug("ASR (faster-whisper) 转写开始, audio size=%d bytes, model=%s",
                  len(audio_bytes), self._model_size)
        try:
            result = await asyncio.to_thread(self._transcribe_sync, audio_bytes)
            log.debug("ASR (faster-whisper) 转写完成: %s...", result[:50])
            return result
        except Exception as e:
            log.error("ASR (faster-whisper) 转写失败: %s\n%s", e, traceback.format_exc())
            raise

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        model = self._load_model()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            segments, _ = model.transcribe(tmp_path)
            return "".join(s.text for s in segments).strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class MockASRService:
    """Mock ASR 用于测试（无 MLX 时使用）"""

    async def transcribe(self, audio_bytes: bytes) -> str:
        return "[mock speech-to-text output]"


def create_asr_service():
    """工厂函数：根据平台自动选择合适的 ASR 后端。

    macOS 优先 mlx-whisper，不可用时降级 faster-whisper。
    其他平台直接使用 faster-whisper。
    """
    if sys.platform == "darwin":
        try:
            import mlx_whisper  # noqa: F401
            return ASRService()
        except ImportError:
            pass
    return FasterWhisperASRService()
