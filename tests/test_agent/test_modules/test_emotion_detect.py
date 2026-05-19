import pytest
from src.agent.context import PipelineContext
from src.agent.modules.prellm.emotion_detect import EmotionDetectModule


class TestEmotionDetectModule:
    def setup_method(self):
        self._module = EmotionDetectModule()

    @pytest.mark.asyncio
    async def test_detect_grief(self):
        ctx = PipelineContext(user_message="奶奶我好想你，真的好难过")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "grief"
        assert ctx.emotion.intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_guilt(self):
        ctx = PipelineContext(user_message="对不起，如果当初我多陪陪你就好了")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "guilt"

    @pytest.mark.asyncio
    async def test_detect_longing(self):
        ctx = PipelineContext(user_message="在那边好吗？我常常想起你")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "longing"

    @pytest.mark.asyncio
    async def test_detect_joy(self):
        ctx = PipelineContext(user_message="奶奶我考上大学了！太棒了！")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "joy"

    @pytest.mark.asyncio
    async def test_detect_anxiety(self):
        ctx = PipelineContext(user_message="我好累，真的不知道怎么撑下去")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "anxiety"

    @pytest.mark.asyncio
    async def test_neutral_when_no_match(self):
        ctx = PipelineContext(user_message="今天天气不错")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "neutral"
        assert ctx.emotion.intensity == 0.3

    @pytest.mark.asyncio
    async def test_intensity_amplified(self):
        ctx = PipelineContext(user_message="我非常想你，真的很想你")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "grief"
        assert ctx.emotion.intensity > 0.6  # amplified by "非常" and "真的"

    @pytest.mark.asyncio
    async def test_short_message_caps_intensity(self):
        ctx = PipelineContext(user_message="想你了")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.intensity <= 0.4

    @pytest.mark.asyncio
    async def test_high_intensity_flag(self):
        ctx = PipelineContext(user_message="我超级想你非常非常想你很难过很想你")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.is_high_intensity is True

    @pytest.mark.asyncio
    async def test_multiple_emotions_picks_highest(self):
        # "想你" hits grief and longing, but grief has higher weight
        ctx = PipelineContext(user_message="想你，又替你开心")
        ctx = await self._module.process(ctx)
        assert ctx.emotion.type == "grief"  # weight 1.3 > 1.0
