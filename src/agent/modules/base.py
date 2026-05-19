from abc import ABC, abstractmethod
from ..context import PipelineContext


class PipelineModule(ABC):
    """Pipeline 模块抽象基类，所有 preprocess/postprocess 模块都继承它"""

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> PipelineContext:
        """处理 Pipeline 上下文并返回更新后的上下文"""
        ...
