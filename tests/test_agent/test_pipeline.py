from src.agent.pipeline import Pipeline


class TestPipeline:
    def test_prellm_module_order(self):
        """prellm 模块按列表顺序排列"""
        pipeline = Pipeline()
        names = [m.__class__.__name__ for m in pipeline._prellm]
        assert names == [
            "MemoryRetrieveModule",
            "CircumstancesModule",
            "EmotionDetectModule",
            "SoulContextModule",
        ]

    def test_postllm_module_order(self):
        """postllm 模块按列表顺序排列"""
        pipeline = Pipeline()
        names = [m.__class__.__name__ for m in pipeline._postllm]
        assert "QualityCheckModule" in names

    def test_postoutput_module_order(self):
        """postoutput 模块按列表顺序排列"""
        pipeline = Pipeline()
        names = [m.__class__.__name__ for m in pipeline._postoutput]
        assert names == [
            "ContextCompressModule",
            "MemoryPersistModule",
            "MemoryExtractModule",
        ]
