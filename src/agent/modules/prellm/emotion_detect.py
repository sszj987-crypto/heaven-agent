from ..base import PipelineModule
from ...context import PipelineContext, EmotionTag
from ....config.logger import get_logger

log = get_logger("emotion_detect")


class EmotionDetectModule(PipelineModule):
    """规则引擎情绪检测器（~5ms，不调用 LLM）"""

    _RULES: dict[str, dict] = {
        "grief": {
            "keywords": ["想你", "好难过", "哭了", "走了", "离开", "失去你", "好想你",
                         "没有你", "再也", "永远", "想你了", "难过", "伤心"],
            "weight": 1.3,
        },
        "guilt": {
            "keywords": ["对不起", "后悔", "如果当初", "都怪我", "没能", "没有陪",
                         "那时候我", "没来得及", "应该陪"],
            "weight": 1.2,
        },
        "longing": {
            "keywords": ["在那边好吗", "你还记得", "常常想起", "梦见你", "念你",
                         "想着你", "每次看到", "又想到你"],
            "weight": 1.0,
        },
        "joy": {
            "keywords": ["好消息", "开心", "高兴", "太棒了", "终于", "成功了", "考上了"],
            "weight": 0.9,
        },
        "anxiety": {
            "keywords": ["担心", "害怕", "迷茫", "压力大", "不知道怎么",
                         "撑不下去", "好累", "好难"],
            "weight": 1.0,
        },
    }

    _INTENSITY_AMPLIFIERS = ["非常", "太", "特别", "超级", "极其", "真的很"]

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        text = ctx.user_message
        log.info("情绪检测开始, text=%s", text[:80])

        scored: dict[str, float] = {}

        for emotion, rule in self._RULES.items():
            score = sum(rule["weight"] for kw in rule["keywords"] if kw in text)
            if score > 0:
                scored[emotion] = score
                log.debug("情绪关键词匹配, emotion=%s, score=%.2f", emotion, score)

        if not scored:
            log.info("情绪检测完成, 未匹配到情绪, type=neutral")
            ctx.emotion = EmotionTag(type="neutral", intensity=0.3, is_high_intensity=False)
            return ctx

        top = max(scored, key=scored.get)
        intensity = min(0.4 + scored[top] * 0.15, 1.0)
        if any(amp in text for amp in self._INTENSITY_AMPLIFIERS):
            intensity = min(intensity + 0.2, 1.0)
            log.debug("检测到强度放大器, intensity+=0.2")
        if len(text) <= 6:
            intensity = min(intensity, 0.4)
            log.debug("短文本, intensity capped at 0.4")

        ctx.emotion = EmotionTag(
            type=top,
            intensity=round(intensity, 2),
            is_high_intensity=intensity >= 0.75,
        )
        log.info("情绪检测完成, type=%s, intensity=%.2f, high=%s",
                 ctx.emotion.type, ctx.emotion.intensity, ctx.emotion.is_high_intensity)
        return ctx
