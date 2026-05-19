from ..base import PipelineModule
from ...context import PipelineContext
from ...pipeline import Pipeline


@Pipeline.register(slot="prellm", order=1)
class CircumstancesModule(PipelineModule):
    """加载当前场景描述"""

    _instance: "CircumstancesModule | None" = None
    _circumstances: str = ""

    def __init__(self):
        CircumstancesModule._instance = self

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        ctx.circumstances = self._circumstances
        return ctx

    @classmethod
    def update(cls, circumstances: str):
        """更新全局场景描述"""
        cls._circumstances = circumstances
