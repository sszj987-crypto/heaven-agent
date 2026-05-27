import pytest
from src.agent.context import PipelineContext
from src.agent.pipeline import Pipeline
from src.agent.modules.base import PipelineModule


class TestPipeline:
    def test_collect_prellm_modules(self):
        """prellm slot 应包含模块"""
        import src.agent.modules.prellm  # 触发注册
        pipeline = Pipeline()
        names = {m.__class__.__name__ for m in pipeline._prellm}
        assert len(names) >= 3
        assert "CircumstancesModule" in names
        assert "EmotionDetectModule" in names
        assert "SoulContextModule" in names

    def test_collect_postllm_modules(self):
        """postllm slot 应包含模块"""
        import src.agent.modules.postllm  # 触发注册
        pipeline = Pipeline()
        names = {m.__class__.__name__ for m in pipeline._postllm}
        assert len(names) >= 1
        assert "QualityCheckModule" in names

    def test_collect_postoutput_modules(self):
        """postoutput slot 应包含模块"""
        import src.agent.modules.postoutput  # 触发注册
        pipeline = Pipeline()
        names = {m.__class__.__name__ for m in pipeline._postoutput}
        assert len(names) >= 2
        assert "ContextCompressModule" in names
        assert "MemoryPersistModule" in names

    def test_modules_sorted_by_order(self):
        """同一 slot 内的模块按 order 排序"""
        pipeline = Pipeline()
        # 检查注册表 key 中的 order 是否与排序一致
        prellm_keys = [(k[0], k[1]) for k in Pipeline._registry if k[0] == "prellm"]
        orders = [k[1] for k in prellm_keys]
        assert orders == sorted(orders)

    def test_register_decorator(self):
        """验证 @Pipeline.register 装饰器能注册新模块"""
        @Pipeline.register(slot="postoutput", order=99)
        class MockOutput(PipelineModule):
            async def process(self, ctx):
                return ctx

        pipeline = Pipeline()
        names = [m.__class__.__name__ for m in pipeline._postoutput]
        assert "MockOutput" in names
