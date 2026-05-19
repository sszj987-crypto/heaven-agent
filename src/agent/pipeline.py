from .context import PipelineContext
from .modules.base import PipelineModule


class Pipeline:
    """三段式 Pipeline，模块通过 @Pipeline.register(slot, order) 自动注册"""

    _registry: dict[str, int, str] = {}  # (slot, order, name) → module_class

    @classmethod
    def register(cls, slot: str, order: int):
        """装饰器：注册到 prellm / postllm / postoutput，按 order 排序执行"""
        def decorator(mod_cls: type[PipelineModule]):
            cls._registry[(slot, order, mod_cls.__name__)] = mod_cls
            return mod_cls
        return decorator

    def __init__(self):
        self._prellm = self._collect("prellm")
        self._postllm = self._collect("postllm")
        self._postoutput = self._collect("postoutput")

    def _collect(self, slot: str) -> list[PipelineModule]:
        items = sorted(
            [(k, v) for k, v in self._registry.items() if k[0] == slot],
            key=lambda x: x[0][1],
        )
        return [mod_cls() for _, mod_cls in items]

    async def run_prellm(self, ctx: PipelineContext) -> PipelineContext:
        for module in self._prellm:
            ctx = await module.process(ctx)
        return ctx

    async def run_postllm(self, ctx: PipelineContext) -> PipelineContext:
        for module in self._postllm:
            ctx = await module.process(ctx)
        return ctx

    async def run_postoutput(self, ctx: PipelineContext) -> PipelineContext:
        for module in self._postoutput:
            ctx = await module.process(ctx)
        return ctx
