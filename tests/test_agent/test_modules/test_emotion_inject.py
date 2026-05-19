import pytest
from src.agent.context import PipelineContext, EmotionTag
from src.agent.modules.postllm.emotion_inject import EmotionInjectModule


class TestEmotionInjectModule:
    def setup_method(self):
        self._module = EmotionInjectModule()

    @pytest.mark.asyncio
    async def test_grief_params(self):
        ctx = PipelineContext(user_message="")
        ctx.emotion = EmotionTag(type="grief")
        ctx = await self._module.process(ctx)
        assert ctx.tts_config.emotion == "gentle"
        assert ctx.tts_config.speed == 0.85
        assert ctx.tts_config.pitch == -2
        assert ctx.tts_config.pause_ms == 500

    @pytest.mark.asyncio
    async def test_joy_params(self):
        ctx = PipelineContext(user_message="")
        ctx.emotion = EmotionTag(type="joy")
        ctx = await self._module.process(ctx)
        assert ctx.tts_config.emotion == "happy"
        assert ctx.tts_config.speed == 1.10
        assert ctx.tts_config.pitch == 3

    @pytest.mark.asyncio
    async def test_neutral_params(self):
        ctx = PipelineContext(user_message="")
        ctx.emotion = EmotionTag(type="neutral")
        ctx = await self._module.process(ctx)
        assert ctx.tts_config.emotion == "neutral"
        assert ctx.tts_config.speed == 1.00

    @pytest.mark.asyncio
    async def test_no_emotion_defaults_to_neutral(self):
        ctx = PipelineContext(user_message="")
        ctx.emotion = None
        ctx = await self._module.process(ctx)
        assert ctx.tts_config.emotion == "neutral"

    @pytest.mark.asyncio
    async def test_unknown_emotion_defaults_to_neutral(self):
        ctx = PipelineContext(user_message="")
        ctx.emotion = EmotionTag(type="surprise")
        ctx = await self._module.process(ctx)
        assert ctx.tts_config.emotion == "neutral"
