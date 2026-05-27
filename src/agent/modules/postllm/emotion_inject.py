from ..base import PipelineModule
from ...context import PipelineContext, TTSConfig
from ...pipeline import Pipeline


@Pipeline.register(slot="postllm", order=2)
class EmotionInjectModule(PipelineModule):
    """根据用户情绪和回复内容，产出 TTS 精细控制参数"""

    # 情绪 → TTS 精细参数
    _TTS_PARAMS: dict[str, dict] = {
        "grief":    {"emotion": "gentle", "speed": 0.85, "pitch": -2, "pause_ms": 500},
        "guilt":    {"emotion": "gentle", "speed": 0.85, "pitch": -1, "pause_ms": 450},
        "longing":  {"emotion": "warm",   "speed": 0.90, "pitch": 0,  "pause_ms": 400},
        "joy":      {"emotion": "happy",  "speed": 1.10, "pitch": 3,  "pause_ms": 250},
        "anxiety":  {"emotion": "calm",   "speed": 0.80, "pitch": -1, "pause_ms": 450},
        "neutral":  {"emotion": "neutral","speed": 1.00, "pitch": 0,  "pause_ms": 300},
    }

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        emo_type = ctx.emotion.type if ctx.emotion else "neutral"
        params = self._TTS_PARAMS.get(emo_type, self._TTS_PARAMS["neutral"])
        ctx.tts_config = TTSConfig(**params)
        return ctx
