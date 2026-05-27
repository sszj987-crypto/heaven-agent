import asyncio
import io
import wave as wav_mod
from pathlib import Path
from typing import AsyncGenerator

import mlx.core as mx
import numpy as np
import soundfile as sf

from ..agent.context import TTSConfig
from ..config.logger import get_logger

log = get_logger("tts")

SAMPLE_RATE = 24_000
REFERENCE_AUDIO_FILE = "reference_audio.wav"

# Emotion → natural language prompt for CosyVoice3 instruct mode
EMOTION_PROMPTS: dict[str, str] = {
    "neutral": "用平静自然的语气说话。",
    "happy": "用开心愉悦的语气说话。",
    "sad": "用温柔安慰的语气说话。",
    "gentle": "用温柔慈祥的语气说话。",
    "warm": "用温暖亲切的语气说话。",
    "calm": "用平和安定的语气说话。",
    "concerned": "用关切担心的语气说话。",
}


class TTSService:
    """本地 TTS 语音合成服务，基于 CosyVoice3 (MLX) 零样本声音克隆"""

    def __init__(self, data_dir: str | Path, model_path: str | None = None):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._ref_audio_path = self._data_dir / REFERENCE_AUDIO_FILE
        self._model = None
        self._model_path = model_path or "./deps/Fun-CosyVoice3-0.5B-2512-8bit"
        log.debug("TTSService 初始化, data_dir=%s, model_path=%s", self._data_dir, self._model_path)

    def _load_model(self):
        """懒加载 CosyVoice3 模型（首次加载约 30-60 秒）"""
        if self._model is not None:
            return self._model

        from mlx_audio.tts.models.cosyvoice3 import Model, ModelConfig

        log.info("正在加载 CosyVoice3 模型（MLX 8-bit, 约 1.3GB）...")
        config = ModelConfig(model_path=self._model_path)
        model = Model(config)
        # Pre-load all components (model weights, tokenizers, speaker encoder)
        model._ensure_model_loaded()
        model._ensure_tokenizers_loaded()
        log.info("CosyVoice3 模型加载完成 (MLX 8-bit, Apple Silicon 原生)")
        self._model = model
        return self._model

    @property
    def has_reference(self) -> bool:
        return self._ref_audio_path.exists()

    def save_reference_audio(self, audio_bytes: bytes) -> None:
        """保存用户上传的参考音频，统一转为 24kHz 单声道 WAV"""
        import subprocess

        raw_path = self._data_dir / "_upload_tmp"
        raw_path.write_bytes(audio_bytes)
        log.debug("原始音频写入临时文件, size=%d bytes", len(audio_bytes))

        try:
            log.debug("使用 ffmpeg 转换音频格式...")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(raw_path),
                    "-ar", str(SAMPLE_RATE), "-ac", "1",
                    "-sample_fmt", "s16",
                    str(self._ref_audio_path),
                ],
                capture_output=True,
                check=True,
            )
            log.debug("ffmpeg 转换成功, 输出=%s", self._ref_audio_path)
        except subprocess.CalledProcessError:
            log.warning("ffmpeg 转换失败，保存原始字节")
            self._ref_audio_path.write_bytes(audio_bytes)
        finally:
            if raw_path.exists():
                raw_path.unlink()

    async def speak(self, text: str, config: TTSConfig | None = None) -> AsyncGenerator[bytes, None]:
        """
        将文字转为语音，流式产出 WAV 音频 bytes。
        使用 CosyVoice3 进行零样本声音克隆 + instruct 情绪控制。
        """
        cfg = config or TTSConfig()

        if not self.has_reference:
            log.debug("没有参考音频，返回空音频")
            yield b""
            return

        log.info("TTS 合成开始, 文本长度=%d, emotion=%s", len(text), cfg.emotion)
        try:
            audio_array = await asyncio.to_thread(
                self._generate,
                text=text,
                emotion=cfg.emotion,
            )
            log.debug("TTS 生成完成, 音频长度=%d samples", audio_array.shape[0])
        except Exception as e:
            log.error("TTS 生成失败: %s", e, exc_info=True)
            yield b""
            return

        # Convert numpy array to 16-bit WAV bytes
        buf = io.BytesIO()
        with wav_mod.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_array * 32767).astype(np.int16).tobytes())
        buf.seek(0)
        audio_bytes = buf.read()
        log.info("TTS 合成完成, WAV 大小=%d bytes", len(audio_bytes))
        yield audio_bytes

    def _generate(self, text: str, emotion: str = "neutral") -> np.ndarray:
        """同步生成音频（在 asyncio.to_thread 中运行）"""
        model = self._load_model()

        # Load reference audio → mx.array at 24kHz
        ref_audio_np, sr = sf.read(str(self._ref_audio_path))
        if ref_audio_np.ndim > 1:
            ref_audio_np = ref_audio_np.mean(axis=1)
        if sr != SAMPLE_RATE:
            from scipy.signal import resample
            duration = len(ref_audio_np) / sr
            num_samples = int(duration * SAMPLE_RATE)
            ref_audio_np = resample(ref_audio_np, num_samples)
        ref_audio_mx = mx.array(ref_audio_np, dtype=mx.float32)

        # Build instruct text for emotion control
        emotion_prompt = EMOTION_PROMPTS.get(emotion, EMOTION_PROMPTS["neutral"])
        instruct_text = f"You are a helpful assistant.{emotion_prompt}<|endofprompt|>"
        log.debug("TTS instruct: %s", instruct_text)

        # Generate audio using CosyVoice3 instruct mode
        results = list(model.generate(
            text=text,
            ref_audio=ref_audio_mx,
            instruct_text=instruct_text,
            stt_model=None,  # Instruct mode doesn't need auto-transcription
            verbose=False,
        ))

        if not results:
            return np.array([], dtype=np.float32)

        # Use the last result (contains the final audio)
        audio = np.array(results[-1].audio).squeeze()

        # Normalize to [-1, 1]
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak

        return audio.astype(np.float32)


class MockTTSService:
    """Mock TTS 用于测试（无 CosyVoice 时使用）"""

    def __init__(self, data_dir: str | Path = "/tmp"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._ref_audio_path = self._data_dir / REFERENCE_AUDIO_FILE

    @property
    def has_reference(self) -> bool:
        return self._ref_audio_path.exists()

    def save_reference_audio(self, audio_bytes: bytes) -> None:
        self._ref_audio_path.write_bytes(audio_bytes)

    async def speak(self, text: str, config: TTSConfig | None = None) -> AsyncGenerator[bytes, None]:
        yield b""
