from ..base import PipelineModule
from ...context import PipelineContext
from ....config.logger import get_logger
from ....services.narrative import NarrativePolicy

log = get_logger("quality_check")
_NARRATIVE_POLICY = NarrativePolicy()


def _append_regeneration_instruction(ctx: PipelineContext, warning: str) -> None:
    """Keep turn-scoped dialect guidance immediately before the retried user input."""
    ctx.llm_messages.append({"role": "system", "content": warning})
    if ctx.dialect_text_instruction:
        ctx.llm_messages.append({
            "role": "system",
            "content": ctx.dialect_text_instruction,
        })
    ctx.llm_messages.append({"role": "user", "content": ctx.user_message})


class QualityCheckModule(PipelineModule):
    """输出质量检查：检测回复文本和语音语气中的禁忌词/极端词，触发 LLM 重新生成"""

    # 只拦截冷漠、推脱式措辞；AI 身份披露本身必须允许。
    _FORBIDDEN_REPLY = [
        "我无法感知",
        "我没有情感",
    ]

    # 语音语气禁忌：极端激烈词汇
    _FORBIDDEN_INSTRUCT = [
        "怒吼", "尖叫", "咆哮", "歇斯底里",
        "哭泣", "哀嚎", "凶恶", "威胁", "恐吓",
        "怒骂", "嘶吼", "狂暴",
    ]

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        log.info(
            "质量检查开始, reply_len=%d, instruct_len=%d",
            len(ctx.response),
            len(ctx.instruct_text),
        )

        if not ctx.response:
            log.debug("响应为空，跳过质量检查")
            return ctx

        narrative_violation = _NARRATIVE_POLICY.output_violation(
            ctx.response,
            afterlife_topic_allowed=ctx.afterlife_topic_allowed,
        )
        if narrative_violation:
            ctx.output_policy_violation = narrative_violation
            _append_regeneration_instruction(
                ctx,
                (
                    "[内部警告] 用户本轮没有主动谈及离世或来世，但上一轮回复主动描述了"
                    "自身的离世状态或来世位置。请完全忽略上一段回复，像普通日常聊天一样回应，"
                    "不要提到天堂、另一个世界、这边或那边的生活状态。"
                ),
            )
            ctx.need_regenerate = True
            log.warning(
                "回复触发未请求的敏感叙事，触发重生成, violation=%s",
                narrative_violation,
            )
            return ctx

        # 检查回复文本
        for pattern in self._FORBIDDEN_REPLY:
            if pattern in ctx.response:
                log.warning("回复文本检测到禁忌词: %s, 触发重生成", pattern)
                _append_regeneration_instruction(
                    ctx,
                    (
                        "[内部警告] 上一轮回复触发了设定约束。"
                        "请完全忽略上一段回复，换个说法重新表达，"
                        "避免用'没有情感''无法感知'等冷漠措辞推脱回应。"
                    ),
                )
                ctx.need_regenerate = True
                return ctx

        # 检查语音语气
        for pattern in self._FORBIDDEN_INSTRUCT:
            if pattern in ctx.instruct_text:
                log.warning("语音语气检测到极端用词: %s, 触发重生成", pattern)
                _append_regeneration_instruction(
                    ctx,
                    (
                        "[内部警告] 上一轮回复的语音语气中出现了极端用词（如'怒吼''咆哮'等）。"
                        "请改用温暖、平静的自然语言语音指导，并确保与 reply 的表达一致。"
                    ),
                )
                ctx.need_regenerate = True
                return ctx

        log.info(
            "质量检查通过, reply_len=%d, instruct_len=%d",
            len(ctx.response),
            len(ctx.instruct_text),
        )
        return ctx
