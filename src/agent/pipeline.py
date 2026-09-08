from .context import PipelineContext
from ..config.logger import get_logger

log = get_logger("pipeline")
_UNSET = object()


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

    def init_deps(
        self,
        message_manager,
        *,
        llm_client=None,
        soul_loader=None,
        memory_store=_UNSET,
        candidate_store=None,
        memory_root=None,
        settings=None,
        job_manager=None,
    ):
        """初始化当前 Pipeline 实例的依赖，避免不同 Soul 共享类级状态。"""
        from ..config.settings import Settings
        from ..llm.manager import get_llm_client
        from ..soul.loader import get_soul_loader
        from .modules.prellm.circumstances import CircumstancesModule
        from .modules.prellm.soul_context import SoulContextModule
        from .modules.prellm.memory_retrieve import MemoryRetrieveModule
        from .modules.postoutput.context_compress import ContextCompressModule
        from .modules.postoutput.memory_persist import MemoryPersistModule
        from .modules.postoutput.memory_extract import MemoryExtractModule

        llm_client = llm_client or get_llm_client()
        soul_loader = soul_loader or get_soul_loader()
        if memory_store is _UNSET:
            from ..memory.store import get_memory_store
            memory_store = get_memory_store()
        settings = settings or Settings.get()
        circumstances = settings.circumstances

        modules = [*self._prellm, *self._postllm, *self._postoutput]
        by_type = {type(module): module for module in modules}

        circumstances_module = by_type[CircumstancesModule]
        circumstances_module._circumstances = circumstances

        soul_module = by_type[SoulContextModule]
        soul_module._loader = soul_loader
        soul_module._messages = message_manager
        soul_module._builder = None

        retrieve_module = by_type[MemoryRetrieveModule]
        retrieve_module._store = memory_store

        compress_module = by_type[ContextCompressModule]
        compress_module._llm = llm_client
        compress_module._messages = message_manager
        compress_module._store = memory_store
        compress_module._crunch_interval = settings.crunch_interval
        compress_module._keep_recent = settings.compress_keep_recent
        compress_module._job_manager = job_manager

        persist_module = by_type[MemoryPersistModule]
        persist_module._messages = message_manager
        if memory_root is not None:
            persist_module._memory_root = memory_root

        extract_module = by_type[MemoryExtractModule]
        extract_module._llm = llm_client
        extract_module._messages = message_manager
        extract_module._loader = soul_loader
        extract_module._candidates = candidate_store
        extract_module._crunch_interval = settings.crunch_interval
        extract_module._job_manager = job_manager

    def update_llm_client(self, client) -> None:
        for module in [*self._prellm, *self._postllm, *self._postoutput]:
            if hasattr(module, "_llm"):
                module._llm = client

    def invalidate_soul_cache(self) -> None:
        for module in self._prellm:
            if module.__class__.__name__ == "SoulContextModule":
                module._cached_prompt = None
                module._builder = None

    def update_circumstances(self, circumstances: str) -> None:
        for module in self._prellm:
            if module.__class__.__name__ == "CircumstancesModule":
                module._circumstances = circumstances
