from ..base import PipelineModule
from ...context import PipelineContext
from ...pipeline import Pipeline
from ....config.logger import get_logger

log = get_logger("circumstances")


@Pipeline.register(slot="prellm", order=1)
class CircumstancesModule(PipelineModule):
    """加载当前场景描述"""

    _instance: "CircumstancesModule | None" = None
    _circumstances: str = ""

    def __init__(self):
        CircumstancesModule._instance = self

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        log.debug("加载场景描述, len=%d chars", len(self._circumstances))
        ctx.circumstances = self._circumstances
        return ctx

    @classmethod
    def update(cls, circumstances: str):
        """更新全局场景描述"""
        log.info("更新场景描述, 新长度=%d chars, preview=%s",
                 len(circumstances), circumstances[:80])
        cls._circumstances = circumstances
