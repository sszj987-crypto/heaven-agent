"""
官方 CosyVoice TTS 后端（PyTorch 原始实现），支持零样本声音克隆。

与 tts.py（MLX 版 CosyVoice3）的区别：
- 使用阿里官方 CosyVoice PyTorch 实现（deps/CosyVoice）
- 模型：CosyVoice-300M（ModelScope）
- 推理设备：CPU（MPS 存在数值不稳定问题，生成"嗯嗯啊啊"乱码）
- 依赖：torch, torchaudio, soundfile, onnxruntime, modelscope, zhconv
"""

import asyncio
import io
import os
import queue
import threading
import time
import wave as wav_mod
from pathlib import Path

import numpy as np

from ..agent.context import TTSConfig
from ..config.logger import get_logger
from .service import VoiceCapabilities

log = get_logger("tts_official")

SAMPLE_RATE = 24_000
REFERENCE_AUDIO_FILE = "reference_audio.wav"
REFERENCE_TEXT_FILE = "reference_text.txt"

# 峰值归一化目标（官方 CosyVoice 推荐 0.8，留有 headroom 避免削波失真）
PEAK_NORM_LEVEL = 0.8
# 尾部静音填充（防止 HiFi-GAN 声码器最后一帧截断导致的爆音/回声）
TRAILING_SILENCE_S = 0.2


class OfficialTTSService:
    """官方 CosyVoice PyTorch 后端，零样本声音克隆"""

    def __init__(self, data_dir: str | Path, model_path: str | None = None):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._ref_audio_path = self._data_dir / REFERENCE_AUDIO_FILE
        self._ref_text_path = self._data_dir / REFERENCE_TEXT_FILE
        self._model = None
        self._model_path = model_path or "iic/CosyVoice-300M"

    def _load_model(self):
        """懒加载官方 CosyVoice 模型（CPU 模式，避免 MPS 数值不稳定）"""
        if self._model is not None:
            return self._model

        # sys.path 注入 CosyVoice 源码
        _cosyvoice_src = Path(__file__).resolve().parent.parent.parent / "deps" / "CosyVoice"
        _matcha_src = _cosyvoice_src / "third_party" / "Matcha-TTS"
        for _src in (str(_matcha_src), str(_cosyvoice_src)):
            if _src not in __import__("sys").path:
                __import__("sys").path.insert(0, _src)

        # ── 在导入 CosyVoice 之前 monkey-patch load_wav ──
        # 新版 torchaudio 的 torchaudio.load(backend='soundfile') 依赖 torchcodec，
        # 这里用 soundfile + torch 重写 load_wav，消除 torchcodec 依赖。
        import cosyvoice.utils.file_utils as _fu

        def _patched_load_wav(wav, target_sr, min_sr=16000):
            import soundfile as _sf
            import torchaudio
            data, sr = _sf.read(wav)
            if data.ndim > 1:
                data = data.mean(axis=1)
            speech = __import__("torch").from_numpy(data).unsqueeze(0).float()
            if sr != target_sr:
                assert sr >= min_sr, f"wav sample rate {sr} must be >= {min_sr}"
                speech = torchaudio.transforms.Resample(
                    orig_freq=sr, new_freq=target_sr
                )(speech)
            return speech

        _fu.load_wav = _patched_load_wav

        from cosyvoice.cli.cosyvoice import CosyVoice

        # ── 解析模型路径：优先使用本地缓存，避免 modelscope 网络请求 ──
        _model_dir = self._model_path
        _local_cache = Path.home() / ".cache" / "modelscope" / "hub" / "models" / _model_dir
        if not os.path.exists(_model_dir) and _local_cache.is_dir():
            _model_dir = str(_local_cache)

        log.info("正在加载官方 CosyVoice 模型（PyTorch CPU 模式）...")
        log.info("模型路径: %s", _model_dir)
        self._model = CosyVoice(_model_dir, fp16=False)
        log.info("官方 CosyVoice 模型加载完成")
        return self._model

    def _transcribe_reference(self) -> str:
        """转写参考音频，返回转写文本（跨平台 ASR）"""
        from .asr import create_asr_service

        asr = create_asr_service()
        log.info("开始转写参考音频（%s）...", type(asr).__name__)
        try:
            import asyncio as _asyncio
            try:
                loop = _asyncio.get_running_loop()
            except RuntimeError:
                loop = _asyncio.new_event_loop()
                _asyncio.set_event_loop(loop)
            text = loop.run_until_complete(asr.transcribe(self._ref_audio_path.read_bytes()))
            log.info("参考音频转写完成: %s", text)
            return text
        except Exception as e:
            log.error("参考音频转写失败: %s", e)
            raise RuntimeError(f"参考音频转写失败: {e}") from e

    @property
    def has_reference(self) -> bool:
        return self._ref_audio_path.exists()

    @property
    def is_ready(self) -> bool:
        return self.has_reference

    @property
    def capabilities(self) -> VoiceCapabilities:
        return VoiceCapabilities(
            requires_reference=True,
            supports_voice_cloning=True,
            supports_instruction=False,
        )

    @property
    def supports_instruction(self) -> bool:
        """The zero-shot PyTorch backend cannot consume per-turn instructions."""
        return False

    def save_reference_audio(self, audio_bytes: bytes) -> None:
        """保存用户上传的参考音频，统一转为 24kHz 单声道 WAV"""
        import subprocess
        import hashlib

        raw_path = self._data_dir / "_upload_tmp"
        raw_path.write_bytes(audio_bytes)
        input_hash = hashlib.sha256(audio_bytes).hexdigest()[:16]
        log.info("保存参考音频, size=%d bytes, input_hash=%s", len(audio_bytes), input_hash)

        try:
            log.debug("使用 ffmpeg 转换音频格式...")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(raw_path),
                    "-ar", str(SAMPLE_RATE), "-ac", "1",
                    "-t", "15",
                    "-sample_fmt", "s16",
                    str(self._ref_audio_path),
                ],
                capture_output=True,
                check=True,
            )
            log.info("ffmpeg 转换成功, output=%s", self._ref_audio_path)
        except (subprocess.CalledProcessError, FileNotFoundError):
            log.warning("ffmpeg 不可用，使用 soundfile 转换格式")
            try:
                import soundfile as sf
                data, sr = sf.read(str(raw_path))
                if data.ndim > 1:
                    data = data.mean(axis=1)
                max_samples = 15 * sr
                if len(data) > max_samples:
                    data = data[:max_samples]
                if sr != SAMPLE_RATE:
                    from scipy.signal import resample_poly
                    data = resample_poly(data, SAMPLE_RATE, sr)
                sf.write(str(self._ref_audio_path), data.astype(np.float32), SAMPLE_RATE, subtype="PCM_16")
                log.info("soundfile 转换成功, output=%s", self._ref_audio_path)
            except Exception as e:
                log.error("soundfile 转换也失败: %s", e)
                raise RuntimeError(f"音频格式转换失败，请上传 WAV/MP3/M4A 格式文件: {e}") from e
        finally:
            if raw_path.exists():
                raw_path.unlink()

        # 转写参考音频文本 → 保存到 ref_text_path
        try:
            ref_text = self._transcribe_reference()
            self._ref_text_path.write_text(ref_text, encoding="utf-8")
            log.info("参考音频文本已保存: %s", self._ref_text_path)
        except Exception as e:
            log.warning("参考音频转写失败（非致命）: %s", e)
            # 使用默认文本
            self._ref_text_path.write_text("这是一段参考语音，用于声音克隆。", encoding="utf-8")

        # 记录最终文件的 hash 供诊断
        final_bytes = self._ref_audio_path.read_bytes()
        final_hash = hashlib.sha256(final_bytes).hexdigest()[:16]
        log.info("参考音频保存完成, file=%s, size=%d, hash=%s",
                 self._ref_audio_path, len(final_bytes), final_hash)

        # 参考音频质量校验
        try:
            import soundfile as sf
            ref_data, _ = sf.read(str(self._ref_audio_path))
            rms = float(np.sqrt(np.mean(ref_data ** 2)))
            peak = float(np.max(np.abs(ref_data)))
            duration = len(ref_data) / SAMPLE_RATE
            if duration < 3.0:
                log.warning("参考音频时长偏短 (%.1fs)，建议使用 5-15 秒清晰语音", duration)
            if peak > 0 and rms > 0:
                snr_est = 20 * np.log10(peak / rms)
                if snr_est < 15:
                    log.warning("参考音频信噪比可能偏低 (%.1fdB)，声音克隆质量可能受影响", snr_est)
        except ImportError:
            log.debug("soundfile 未安装，跳过参考音频质量诊断")

    async def speak(self, text: str, config: TTSConfig | None = None) -> list[bytes]:
        """
        将文字转为语音，返回 WAV 音频 bytes。
        注意：官方 CosyVoice 不支持 instruct 模式，仅零样本声音克隆。
        """
        if not self.has_reference:
            log.debug("没有参考音频，返回空音频")
            yield b""
            return

        log.info("TTS (official) 合成开始, text_len=%d", len(text))
        t0 = time.monotonic()

        chunk_queue: queue.Queue = queue.Queue()

        def _run_generation():
            try:
                audio_array = self._generate(text)
                chunk_queue.put(audio_array)
            except Exception as e:
                chunk_queue.put(e)
            finally:
                chunk_queue.put(None)

        thread = threading.Thread(target=_run_generation, daemon=True)
        thread.start()

        audio_array = None
        while True:
            item = await asyncio.to_thread(chunk_queue.get)
            if item is None:
                break
            if isinstance(item, Exception):
                log.error("TTS 生成失败: %s", item,
                          exc_info=(type(item), item, item.__traceback__))
                raise item
            audio_array = item

        if audio_array is None or audio_array.shape[0] == 0:
            yield b""
            return

        # 峰值归一化
        peak = np.max(np.abs(audio_array))
        if peak > 1e-8:
            audio_normalized = audio_array / peak * PEAK_NORM_LEVEL
        else:
            audio_normalized = audio_array

        # 尾部静音填充
        silence_samples = int(TRAILING_SILENCE_S * SAMPLE_RATE)
        audio_padded = np.pad(audio_normalized, (0, silence_samples), mode="constant")

        audio_int16 = (audio_padded * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wav_mod.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())
        buf.seek(0)
        audio_bytes = buf.read()
        elapsed = time.monotonic() - t0
        duration_s = audio_array.shape[0] / SAMPLE_RATE
        log.info("TTS (official) 合成完成, WAV_size=%d bytes, duration=%.1fs, elapsed=%.1fs, rtf=%.2f",
                 len(audio_bytes), duration_s, elapsed, elapsed / duration_s if duration_s > 0 else 0)
        yield audio_bytes

    def _generate(self, text: str) -> np.ndarray:
        """同步生成音频：零样本声音克隆，stream=True 流式推理"""
        import torch

        t0 = time.monotonic()
        model = self._load_model()

        # 1. 标点符号强化：确保结尾有停顿标记
        text = text.strip()
        eos_markers = ('.', '!', '?', '。', '！', '？', '…', '~', '～', '"', '"', '\u3000')
        if text and not text.endswith(eos_markers):
            last_char = text[-1]
            if '\u4e00' <= last_char <= '\u9fff' or last_char.isalnum():
                text = text + '。'

        # 2. 加载 prompt_text（繁体→简体转换）
        prompt_text = self._ref_text_path.read_text(encoding="utf-8").strip()
        try:
            import zhconv
            prompt_simplified = zhconv.convert(prompt_text, "zh-cn")
            if prompt_simplified != prompt_text:
                log.info("prompt_text 繁体→简体: %s → %s", prompt_text, prompt_simplified)
                prompt_text = prompt_simplified
        except Exception:
            pass

        # 3. prompt_wav 路径
        prompt_wav = str(self._ref_audio_path)

        log.debug("TTS (official) inference_zero_shot, text=%s, prompt_text=%s, prompt_wav=%s",
                  text, prompt_text, prompt_wav)

        # 4. 流式推理
        t_gen = time.monotonic()
        audio_chunks = []
        chunk_count = 0
        for model_output in model.inference_zero_shot(
            tts_text=text,
            prompt_text=prompt_text,
            prompt_wav=prompt_wav,
            stream=True,
        ):
            speech = model_output["tts_speech"]
            # speech 是 torch.Tensor，shape: (1, samples)
            audio_chunks.append(speech.detach().cpu().numpy().squeeze())
            chunk_count += 1
            if chunk_count == 1:
                first = audio_chunks[0]
                log.info("TTS (official) 首片: samples=%d, peak=%.3f, mean=%.6f",
                         len(first), float(np.max(np.abs(first))),
                         float(np.mean(np.abs(first))))

        elapsed_gen = time.monotonic() - t_gen
        if chunk_count == 0:
            log.warning("TTS (official) inference_zero_shot 返回空")
            return np.array([], dtype=np.float32)

        audio = np.concatenate(audio_chunks)

        log.debug("_generate 总耗时=%.2fs, gen=%.2fs, chunks=%d, audio_shape=%s, peak=%.3f",
                  time.monotonic() - t0, elapsed_gen, chunk_count, audio.shape,
                  float(np.max(np.abs(audio))))
        return audio.astype(np.float32)
