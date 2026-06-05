"""记忆检索模块：在 LLM 调用前，从 ChromaDB 检索与用户消息相关的记忆。

检索结果注入 PipelineContext.retrieved_memories，供 SoulContextModule 拼入 prompt。
"""

from ..base import PipelineModule
from ...context import PipelineContext
from ....memory.store import MemoryStore
from ....config.logger import get_logger

log = get_logger("memory_retrieve")

DEFAULT_TOP_K = 5


class MemoryRetrieveModule(PipelineModule):
    """PreLLM 第一阶段：语义检索相关记忆（在 SoulContext 之前执行）"""

    _store: MemoryStore | None = None
    _top_k: int = DEFAULT_TOP_K

    @classmethod
    def set_deps(cls, store: MemoryStore, top_k: int = DEFAULT_TOP_K):
        cls._store = store
        cls._top_k = top_k

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        if self._store is None or self._store.count == 0:
            log.debug("记忆库为空，跳过检索")
            ctx.retrieved_memories = []
            return ctx

        query = ctx.user_message
        if not query.strip():
            ctx.retrieved_memories = []
            return ctx

        try:
            results = self._store.search(query, top_k=self._top_k)
            ctx.retrieved_memories = results
            if results:
                dims = list({r["metadata"].get("dimension", "?") for r in results})
                log.info("记忆检索: query='%s' → %d 条, dimensions=%s",
                         query[:40], len(results), dims)
                log.debug("检索详情:\n%s",
                          "\n".join(f"  [{r['metadata'].get('dimension','?')}] "
                                    f"dist={r['distance']:.3f} {r['document'][:80]}"
                                    for r in results))
            else:
                log.debug("记忆检索无结果, query='%s'", query[:40])
        except Exception as e:
            log.error("记忆检索失败: %s", e)
            ctx.retrieved_memories = []

        return ctx
