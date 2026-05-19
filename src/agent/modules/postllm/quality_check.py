from ..base import PipelineModule
from ...context import PipelineContext
from ...pipeline import Pipeline


@Pipeline.register(slot="postllm", order=1)
class QualityCheckModule(PipelineModule):
    """输出质量检查：检测禁忌词，触发 LLM 重新生成"""

    _FORBIDDEN = [
        "作为AI", "作为人工智能", "我是语言模型", "我无法感知",
        "我没有情感", "作为助手", "AI助手", "语言模型",
    ]

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.response:
            return ctx

        for pattern in self._FORBIDDEN:
            if pattern in ctx.response:
                # 追加警告消息，让 LLM 换个说法重新生成
                ctx.llm_messages.append({
                    "role": "system",
                    "content": (
                        "[内部警告] 上一轮回复触发了设定约束。"
                        "请完全忽略上一段回复，换个说法重新表达，"
                        "不要出现'作为AI''语言模型''无法感知'等表述。"
                    ),
                })
                ctx.llm_messages.append({"role": "user", "content": ctx.user_message})
                ctx.need_regenerate = True
                return ctx

        return ctx
