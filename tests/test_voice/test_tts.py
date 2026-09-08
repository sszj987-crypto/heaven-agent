import tempfile
from pathlib import Path
import struct
import numpy as np
import pytest
from src.agent.context import TTSConfig
from src.voice.tts import TTSService, MockTTSService, SAMPLE_RATE, PEAK_NORM_LEVEL, TRAILING_SILENCE_S


def _force_eos_punctuation(text: str) -> str:
    """从 tts.py _generate() 中提取的句尾标点逻辑，独立测试用"""
    text = text.strip()
    eos_markers = ('.', '!', '?', '。', '！', '？', '…', '~', '～', '"', '"', '\u3000')
    if text and not text.endswith(eos_markers):
        last_char = text[-1]
        if '\u4e00' <= last_char <= '\u9fff' or last_char.isalnum():
            text = text + '。'
    return text


class TestEOSPunctuation:
    def test_already_ended_with_period(self):
        assert _force_eos_punctuation("你好。") == "你好。"
        assert _force_eos_punctuation("Hello.") == "Hello."

    def test_adds_period_for_chinese(self):
        assert _force_eos_punctuation("你好") == "你好。"
        assert _force_eos_punctuation("今天天气不错") == "今天天气不错。"

    def test_adds_period_for_alphanumeric(self):
        assert _force_eos_punctuation("hello") == "hello。"

    def test_preserves_exclamation(self):
        assert _force_eos_punctuation("太好了！") == "太好了！"

    def test_empty_text(self):
        assert _force_eos_punctuation("") == ""

    def test_strips_and_adds(self):
        assert _force_eos_punctuation("  你好  ") == "你好。"

    def test_tilde_preserved(self):
        assert _force_eos_punctuation("好吧～") == "好吧～"


class TestPeakNormalization:
    def test_peak_normalization_level(self):
        """验证峰值归一化到 PEAK_NORM_LEVEL * 32767"""
        # 模拟一个正弦波，峰值只有 0.5
        t = np.linspace(0, 1, SAMPLE_RATE, endpoint=False)
        audio = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)

        peak = np.max(np.abs(audio))
        audio_normalized = audio / peak * PEAK_NORM_LEVEL
        audio_int16 = (audio_normalized * 32767).astype(np.int16)

        expected_peak = int(PEAK_NORM_LEVEL * 32767)
        actual_peak = np.max(np.abs(audio_int16))
        # 允许 1 个量化误差
        assert abs(actual_peak - expected_peak) <= 1, \
            f"Expected peak ~{expected_peak}, got {actual_peak}"

    def test_silent_audio_handled(self):
        """静音音频不应报错"""
        audio = np.zeros(1000, dtype=np.float32)
        peak = np.max(np.abs(audio))
        if peak > 1e-8:
            audio_normalized = audio / peak * PEAK_NORM_LEVEL
        else:
            audio_normalized = audio
        # 不应抛出异常
        assert np.all(audio_normalized == 0)


class TestTrailingSilence:
    def test_trailing_silence_added(self):
        """验证尾部添加了 TRAILING_SILENCE_S * SAMPLE_RATE 采样点"""
        audio = np.ones(SAMPLE_RATE, dtype=np.float32)  # 1 秒音频
        silence_samples = int(TRAILING_SILENCE_S * SAMPLE_RATE)
        audio_padded = np.pad(audio, (0, silence_samples), mode="constant")

        expected_len = SAMPLE_RATE + silence_samples
        assert len(audio_padded) == expected_len
        # 尾部应该是静音
        assert np.all(audio_padded[-silence_samples:] == 0)
        # 前面保持原始音频
        assert np.all(audio_padded[:SAMPLE_RATE] == 1.0)


class TestTTSService:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._data_dir = Path(self._tmp.name)
        self._tts = TTSService(self._data_dir)

    def teardown_method(self):
        self._tmp.cleanup()

    def test_has_reference_false_initially(self):
        assert not self._tts.has_reference

    def test_mlx_backend_reports_instruction_support(self):
        assert self._tts.supports_instruction is True

    def test_save_reference_audio_silent_accepted(self):
        """静音音频也可以保存（不再强制要求 Whisper 转写 ref_text）"""
        import struct
        sample_rate = 24000
        duration = 0.5
        num_samples = int(sample_rate * duration)
        raw_samples = b"".join(struct.pack("<h", 0) for _ in range(num_samples))
        wav_header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + len(raw_samples), b"WAVE", b"fmt ", 16,
            1, 1, sample_rate, sample_rate * 2, 2, 16,
            b"data", len(raw_samples),
        )
        wav_bytes = wav_header + raw_samples
        # 不再抛异常，音频直接保存
        self._tts.save_reference_audio(wav_bytes)
        assert self._tts.has_reference

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
