import asyncio
import io
import queue
import threading
import time
import wave as wav_mod
from pathlib import Path
from typing import AsyncGenerator

import numpy as np

from ..agent.context import TTSConfig
from ..config.logger import get_logger

log = get_logger("tts")

SAMPLE_RATE = 24_000
REFERENCE_AUDIO_FILE = "reference_audio.wav"


# 峰值归一化目标（官方 CosyVoice3 推荐 0.8，留有 headroom 避免削波失真）
PEAK_NORM_LEVEL = 0.8
# 尾部静音填充（防止 HiFi-GAN 声码器最后一帧截断导致的爆音/回声）
TRAILING_SILENCE_S = 0.2


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

        # mlx_audio 的 fetch_from_hub() 调用 snapshot_download() 时未传 local_files_only=True，
        # 导致即使缓存已存在也会先调 api.repo_info() 发起 HTTPS 请求。
        # 若网络不通，SSLError 在 snapshot_download 内部被显式 re-raise，不会回退到本地缓存。
        # 这里仅在 S3TokenizerV3 加载期间 monkey-patch snapshot_download，
        # 加载完立即恢复，避免影响后续其他模型下载。
        # 注意：不能用 HF_HUB_OFFLINE 环境变量，因为 huggingface_hub 在模块导入时
        # 将其缓存为常量，后续修改环境变量无效，且会永久阻断所有下载。
        from pathlib import Path as _Path

        _cache = _Path.home() / ".cache/huggingface/hub/models--mlx-community--S3TokenizerV3"
        _cache_exists = _cache.exists()

        _patch_applied = False
        _original_snapshot = None
        if _cache_exists:
            import huggingface_hub as _hfh
            _original_snapshot = _hfh.snapshot_download

            def _offline_snapshot_download(repo_id, **kwargs):
                kwargs["local_files_only"] = True
                return _original_snapshot(repo_id, **kwargs)

            _hfh.snapshot_download = _offline_snapshot_download
            _patch_applied = True
            log.info("S3TokenizerV3 缓存已存在 (%s)，使用离线模式加载", _cache)
        else:
            log.info("S3TokenizerV3 缓存不存在，首次运行将自动从 HuggingFace 下载...")

        from mlx_audio.tts.models.cosyvoice3 import Model, ModelConfig

        log.info("正在加载 CosyVoice3 模型（MLX 8-bit, 约 1.3GB）...")
        config = ModelConfig(model_path=self._model_path)
        model = Model(config)
        model._ensure_model_loaded()

        try:
            model._ensure_tokenizers_loaded()
        except Exception as e:
            if not _cache_exists:
                log.error(
                    "S3TokenizerV3 下载失败，请检查网络连接。"
                    "若网络正常但仍失败，可手动下载："
                    "git clone https://huggingface.co/mlx-community/S3TokenizerV3 %s",
                    _cache,
                )
            raise
        finally:
            # 恢复原始 snapshot_download，避免影响后续其他模型下载
            if _patch_applied and _original_snapshot is not None:
                import huggingface_hub as _hfh
                _hfh.snapshot_download = _original_snapshot
                log.debug("snapshot_download monkey-patch 已恢复")

        log.info("CosyVoice3 模型加载完成 (MLX 8-bit, Apple Silicon 原生)")
        self._model = model
        return self._model

    @property
    def has_reference(self) -> bool:
        return self._ref_audio_path.exists()

    @property
    def supports_instruction(self) -> bool:
        return True

    def save_reference_audio(self, audio_bytes: bytes) -> None:
        """保存用户上传的参考音频，统一转为 24kHz 单声道 WAV"""
        import subprocess
        import hashlib

        raw_path = self._data_dir / "_upload_tmp"
        raw_path.write_bytes(audio_bytes)
        input_hash = hashlib.sha256(audio_bytes).hexdigest()[:16]
        log.info("保存参考音频, size=%d bytes, input_hash=%s", len(audio_bytes), input_hash)

        try:
            log.debug("使用 ffmpeg 转换音频格式并优化质量...")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(raw_path),
                    "-ar", str(SAMPLE_RATE), "-ac", "1",
                    # 截取前 8 秒（CosyVoice 官方推荐 5-8s 参考音频）
                    # MLX generate() 内部已通过 librosa.effects.trim(top_db=60) 处理静音切除，
                    # 这里仅做格式转换，避免 loudnorm 改变波形动态特征干扰 CAMPlus 编码器
                    "-t", "8",
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
                # 截取前 10 秒
                max_samples = 10 * sr
                if len(data) > max_samples:
                    data = data[:max_samples]
                if sr != SAMPLE_RATE:
                    from scipy.signal import resample
                    n_samples = int(len(data) * SAMPLE_RATE / sr)
                    data = resample(data, n_samples)
                sf.write(str(self._ref_audio_path), data.astype(np.float32), SAMPLE_RATE, subtype="PCM_16")
                log.info("soundfile 转换成功, output=%s", self._ref_audio_path)
            except Exception as e:
                log.error("soundfile 转换也失败: %s", e)
                raise RuntimeError(f"音频格式转换失败，请上传 WAV/MP3/M4A 格式文件: {e}") from e
        finally:
            if raw_path.exists():
                raw_path.unlink()

        # 记录最终文件的 hash 供诊断
        final_bytes = self._ref_audio_path.read_bytes()
        final_hash = hashlib.sha256(final_bytes).hexdigest()[:16]
        log.info("参考音频保存完成, file=%s, size=%d, hash=%s",
                 self._ref_audio_path, len(final_bytes), final_hash)

        # 参考音频质量校验（诊断用，不阻塞流程）
        try:
            import soundfile as sf
            ref_data, _ = sf.read(str(self._ref_audio_path))
            rms = float(np.sqrt(np.mean(ref_data ** 2)))
            peak = float(np.max(np.abs(ref_data)))
            duration = len(ref_data) / SAMPLE_RATE
            if duration < 3.0:
                log.warning("参考音频时长偏短 (%.1fs)，建议使用 5-8 秒清晰语音", duration)
            if peak > 0 and rms > 0:
                snr_est = 20 * np.log10(peak / rms)
                if snr_est < 15:
                    log.warning("参考音频信噪比可能偏低 (%.1fdB)，声音克隆质量可能受影响", snr_est)
        except ImportError:
            log.debug("soundfile 未安装，跳过参考音频质量诊断")


    async def speak(self, text: str, config: TTSConfig | None = None) -> AsyncGenerator[bytes, None]:
        """
        将文字转为语音，流式产出 WAV 音频 bytes。
        Instruct 模式声音克隆。
        """
        cfg = config or TTSConfig()

        if not self.has_reference:
            log.debug("没有参考音频，返回空音频")
            yield b""
            return

        log.info("TTS 合成开始, text_len=%d, instruct=%s", len(text), cfg.instruct_text)
        t0 = time.monotonic()

        # 队列在线程间传递音频数据，实现真正的流式下发
        chunk_queue: queue.Queue = queue.Queue()

        def _run_generation():
            try:
                audio_array = self._generate(text=text, instruct_text=cfg.instruct_text)
                chunk_queue.put(audio_array)
            except Exception as e:
                chunk_queue.put(e)
            finally:
                chunk_queue.put(None)  # sentinel

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

        # 峰值归一化到目标电平（匹配官方 CosyVoice3 后处理，避免硬裁剪失真）
        peak = np.max(np.abs(audio_array))
        if peak > 1e-8:
            audio_normalized = audio_array / peak * PEAK_NORM_LEVEL
        else:
            audio_normalized = audio_array

        # 尾部静音填充（防止声码器最后一帧截断产生爆音/回声）
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
        log.info("TTS 合成完成, WAV_size=%d bytes, duration=%.1fs, elapsed=%.1fs, rtf=%.2f",
                 len(audio_bytes), duration_s, elapsed, elapsed / duration_s if duration_s > 0 else 0)
        yield audio_bytes

    def _generate(self, text: str, instruct_text: str = "") -> np.ndarray:
        """同步生成音频：Instruct 模式 + 说话人嵌入驱动声音克隆。
        所有情感表达通过 LLM 生成的标点和语气词（…、~、！、呢、呀）驱动。
        """
        t0 = time.monotonic()
        try:
            import mlx.core as mx
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError(
                "MLX 语音依赖未安装，请运行 scripts/bootstrap.py --voice"
            ) from exc
        model = self._load_model()

        # 1. 标点符号强化：确保结尾有停顿标记，有效减少「尾音复读机」幻觉
        text = text.strip()
        eos_markers = ('.', '!', '?', '。', '！', '？', '…', '~', '～', '"', '"', '\u3000')
        if text and not text.endswith(eos_markers):
            last_char = text[-1]
            if '\u4e00' <= last_char <= '\u9fff' or last_char.isalnum():
                text = text + '。'

        # 2. 加载参考音频 → mx.array（24kHz）
        ref_audio_np, sr = sf.read(str(self._ref_audio_path))
        if ref_audio_np.ndim > 1:
            ref_audio_np = ref_audio_np.mean(axis=1)
        if sr != SAMPLE_RATE:
            from scipy.signal import resample
            num_samples = int((len(ref_audio_np) / sr) * SAMPLE_RATE)
            ref_audio_np = resample(ref_audio_np, num_samples)
        ref_audio_mx = mx.array(ref_audio_np, dtype=mx.float32)
        log.info("参考音频加载, path=%s, shape=%s, sr=%d, duration=%.1fs",
                 self._ref_audio_path, ref_audio_mx.shape, sr,
                 len(ref_audio_np) / sr)

        # CosyVoice3 训练格式: "You are a helpful assistant.{指令}<|endofprompt|>{文本}"
        # "You are a helpful assistant." 是区分指令和文本的关键标记，不可省略
        # <|endofprompt|> 由 model.generate() 自动追加
        full_instruct = f"You are a helpful assistant.{instruct_text}"
        log.debug("TTS instruct: %s", full_instruct)

        t_gen = time.monotonic()
        results = list(model.generate(
            text=text,
            ref_audio=ref_audio_mx,
            instruct_text=full_instruct,
            stt_model=None,
            verbose=False,
        ))
        log.debug("model.generate 耗时=%.2fs, chunks=%d", time.monotonic() - t_gen, len(results))

        if not results:
            log.warning("TTS model.generate 返回空结果")
            return np.array([], dtype=np.float32)

        audio = np.array(results[-1].audio).squeeze()

        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak

        log.debug("_generate 总耗时=%.2fs, audio_shape=%s, peak=%.3f",
                  time.monotonic() - t0, audio.shape, peak)
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

    @property
    def supports_instruction(self) -> bool:
        return True

    def save_reference_audio(self, audio_bytes: bytes) -> None:
        self._ref_audio_path.write_bytes(audio_bytes)

    async def speak(self, text: str, config: TTSConfig | None = None) -> AsyncGenerator[bytes, None]:
        yield b""
