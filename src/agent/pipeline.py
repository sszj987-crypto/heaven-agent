from .context import PipelineContext
from ..config.logger import get_logger

log = get_logger("pipeline")


class Pipeline:
    """三段式 Pipeline，模块按注册表顺序执行。

    顺序由列表位置决定，不再需要 order 数字。
    新增模块只需在对应 slot 列表中添加即可。
    """

    def __init__(self):
        # 延迟 import 避免循环依赖
        from .modules.prellm.memory_retrieve import MemoryRetrieveModule
        from .modules.prellm.circumstances import CircumstancesModule
        from .modules.prellm.emotion_detect import EmotionDetectModule
        from .modules.prellm.soul_context import SoulContextModule
        from .modules.postllm.quality_check import QualityCheckModule
        from .modules.postllm.style_refine import StyleRefineModule
        from .modules.postoutput.context_compress import ContextCompressModule
        from .modules.postoutput.memory_persist import MemoryPersistModule
        from .modules.postoutput.memory_extract import MemoryExtractModule

        self._prellm = [
            MemoryRetrieveModule(),
            CircumstancesModule(),
            EmotionDetectModule(),
            SoulContextModule(),
        ]
        self._postllm = [
            QualityCheckModule(),
            StyleRefineModule(),
        ]
        self._postoutput = [
            ContextCompressModule(),
            MemoryPersistModule(),
            MemoryExtractModule(),
        ]
        log.debug("Pipeline 初始化, prellm=%d, postllm=%d, postoutput=%d",
                  len(self._prellm), len(self._postllm), len(self._postoutput))

    async def run_prellm(self, ctx: PipelineContext) -> PipelineContext:
        log.info("── PreLLM 阶段开始（%d 个模块）──", len(self._prellm))
        for module in self._prellm:
            log.debug("PreLLM: 执行 %s", module.__class__.__name__)
            ctx = await module.process(ctx)
        log.info("── PreLLM 阶段完成, messages=%d, emotion=%s ──",
                 len(ctx.llm_messages), ctx.emotion.type if ctx.emotion else "None")
        return ctx

    async def run_postllm(self, ctx: PipelineContext) -> PipelineContext:
        log.info("── PostLLM 阶段开始（%d 个模块）──", len(self._postllm))
        for module in self._postllm:
            log.debug("PostLLM: 执行 %s", module.__class__.__name__)
            ctx = await module.process(ctx)
        log.info("── PostLLM 阶段完成, response_len=%d, need_regenerate=%s ──",
                 len(ctx.response), ctx.need_regenerate)
        return ctx

    async def run_postoutput(self, ctx: PipelineContext) -> PipelineContext:
        log.info("── PostOutput 阶段开始（%d 个模块）──", len(self._postoutput))
        for module in self._postoutput:
            log.debug("PostOutput: 执行 %s", module.__class__.__name__)
            ctx = await module.process(ctx)
        log.info("── PostOutput 阶段完成 ──")
        return ctx

    @classmethod
    def init_deps(cls, message_manager):
        """一次性初始化所有 Pipeline 模块的依赖（在 AgentLoop 构造时调用）。"""
        from ..config.settings import Settings
        from ..llm.manager import get_llm_client
        from ..soul.loader import get_soul_loader
        from ..memory.store import get_memory_store
        from .modules.prellm.circumstances import CircumstancesModule
        from .modules.prellm.soul_context import SoulContextModule
        from .modules.prellm.memory_retrieve import MemoryRetrieveModule
        from .modules.postoutput.context_compress import ContextCompressModule
        from .modules.postoutput.memory_persist import MemoryPersistModule
        from .modules.postoutput.memory_extract import MemoryExtractModule
        from .modules.postllm.style_refine import StyleRefineModule

        llm_client = get_llm_client()
        soul_loader = get_soul_loader()
        memory_store = get_memory_store()
        circumstances = Settings.get().circumstances

        CircumstancesModule.update(circumstances)
        SoulContextModule.set_deps(soul_loader, message_manager)
        StyleRefineModule.set_deps(llm_client, soul_loader)
        ContextCompressModule.set_deps(llm_client, message_manager)
        MemoryPersistModule.set_deps(message_manager)
        if memory_store:
            MemoryRetrieveModule.set_deps(memory_store)
            ContextCompressModule.set_deps(llm_client, message_manager, memory_store)
            MemoryExtractModule.set_deps(llm_client, message_manager, soul_loader)
