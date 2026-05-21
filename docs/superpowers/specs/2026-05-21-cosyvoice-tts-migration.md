# CosyVoice TTS Migration — Design Spec

## Overview

Replace F5-TTS-MLX with **CosyVoice2-0.5B** for Chinese voice cloning TTS. CosyVoice offers natural language emotion control, direct Python API integration, and stable Mac/Windows cross-platform support.

## Why CosyVoice

| Pain point with F5-TTS-MLX | CosyVoice fix |
|---|---|
| Manual duration estimation for Chinese (byte-based) | No duration needed — handles internally |
| Reference audio bleeding into output (trimming bugs) | No manual trimming — handles internally |
| No explicit emotion control | Natural language emotion prompts ("用温柔的语气") |
| MLX-only (Apple Silicon exclusive) | PyTorch — Mac/Windows/Linux, CPU/MPS/CUDA |

## Model Selection

- **Primary**: CosyVoice2-0.5B (stable, mature)
- **Future upgrade path**: CosyVoice3-0.5B (released Dec 2025, requires macOS 15+)

## Architecture

### Device Detection (cross-platform with graceful degradation)

```
macOS  → attempt MPS → verify with torch test → fallback CPU
Linux  → attempt CUDA → verify              → fallback CPU
Windows → attempt CUDA → verify              → fallback CPU
```

```python
def _detect_device() -> str:
    import torch
    if torch.backends.mps.is_available():
        try:
            torch.zeros(1).to("mps")
            return "mps"
        except Exception:
            pass
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
```

### Emotion Injection

Existing `EmotionInjectModule` → `TTSConfig.emotion` → natural language prompt:

```python
EMOTION_PROMPTS = {
    "neutral": "用平静自然的语气说话。",
    "happy": "用开心愉悦的语气说话。",
    "sad": "用温柔安慰的语气说话。",
    "gentle": "用温柔慈祥的语气说话。",
    "concerned": "用关切担心的语气说话。",
    "default": "用{emotion}的语气说话。",
}
```

Use CosyVoice's `inference_instruct2()` when emotion is specified, fallback to `inference_zero_shot()` for neutral.

### Reference Audio

- Keep existing upload flow: user uploads audio → save as `reference_audio.wav` via ffmpeg (24kHz mono)
- Default ref text: `"你好，这是我的一段语音。"` (unchanged)
- CosyVoice expects prompt_speech at 16kHz → resample internally

### Code Changes

| File | Change |
|------|--------|
| `src/voice/tts.py` | Rewrite `_generate()` to use CosyVoice; add device detection; add emotion prompt mapping; remove all duration/trimming logic |
| `src/voice/tts.py` | Add `_detect_device()` function |
| `config/voice.json` | Add `model_dir` field (path to CosyVoice pretrained models) |
| `pyproject.toml` | Add `torch`, `torchaudio`, `cosyvoice` dependencies |

### What stays unchanged

- `speak(text, config) → AsyncGenerator[bytes]` interface
- `save_reference_audio()` method
- `MockTTSService` (test mock)
- `TTSService.__init__(data_dir)` constructor signature
- API routes (`/chat`, `/chat/audio`, etc.)
- Frontend (no changes needed)

### New TTS class structure

```python
class TTSService:
    def __init__(self, data_dir, model_dir=None):
        self._data_dir = Path(data_dir)
        self._ref_audio_path = self._data_dir / REFERENCE_AUDIO_FILE
        self._model_dir = model_dir or "pretrained_models/CosyVoice2-0.5B"
        self._model = None
        self._device = _detect_device()

    def _load_model(self):
        if self._model is None:
            from cosyvoice.cli.cosyvoice import CosyVoice2
            self._model = CosyVoice2(
                self._model_dir,
                load_jit=False,
                fp16=(self._device != "cpu"),
                device=self._device,
            )

    def _generate(self, text, speed=1.0):
        model = self._load_model()
        prompt_audio, prompt_sr = torchaudio.load(self._ref_audio_path)
        if prompt_sr != 16000:
            prompt_audio = torchaudio.functional.resample(prompt_audio, prompt_sr, 16000)

        emotion = ... # from caller context
        if emotion and emotion != "neutral":
            instruct = EMOTION_PROMPTS.get(emotion, EMOTION_PROMPTS["default"].format(emotion=emotion))
            result = model.inference_instruct2(text, instruct, prompt_audio, prompt_text=DEFAULT_REF_TEXT)
        else:
            result = model.inference_zero_shot(text, prompt_audio, prompt_text=DEFAULT_REF_TEXT)

        audio = result["tts_speech"].numpy().flatten()
        # Resample from 22050 to SAMPLE_RATE (24000) if needed
        ...
        return audio.astype(np.float32)
```

## Testing

- Unit test: `MockTTSService` already exists, no changes needed
- Integration test: verify `_detect_device()` returns valid device string on current platform
- Manual test: upload reference audio → send chat message → verify audio plays correctly

## Migration Steps

1. Install dependencies: `pip install torch torchaudio cosyvoice modelscope`
2. Download model: `python -c "from modelscope import snapshot_download; snapshot_download('iic/CosyVoice2-0.5B', local_dir='pretrained_models/CosyVoice2-0.5B')"`
3. Rewrite `src/voice/tts.py` `_generate()` and add `_detect_device()`
4. Update `config/voice.json`
5. Remove F5-TTS-MLX specific imports and code
6. Test on macOS (MPS → CPU fallback)
