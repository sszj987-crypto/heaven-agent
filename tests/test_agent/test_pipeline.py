from src.agent.pipeline import Pipeline


class FakeSettings:
    circumstances = ""
    crunch_interval = 10
    compress_keep_recent = 6


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

    def test_dependency_state_is_isolated_per_pipeline(self):
        first = Pipeline()
        second = Pipeline()
        first_loader = object()
        second_loader = object()
        first_messages = object()
        second_messages = object()

        first.init_deps(
            first_messages,
            llm_client=object(),
            soul_loader=first_loader,
            memory_store=None,
            candidate_store=object(),
            settings=FakeSettings(),
        )
        second.init_deps(
            second_messages,
            llm_client=object(),
            soul_loader=second_loader,
            memory_store=None,
            candidate_store=object(),
            settings=FakeSettings(),
        )

        first_soul = next(m for m in first._prellm if m.__class__.__name__ == "SoulContextModule")
        second_soul = next(m for m in second._prellm if m.__class__.__name__ == "SoulContextModule")
        first_extract = next(m for m in first._postoutput if m.__class__.__name__ == "MemoryExtractModule")

        assert first_soul._loader is first_loader
        assert second_soul._loader is second_loader
        assert first_soul._loader is not second_soul._loader
        assert first_extract._candidates is not None
