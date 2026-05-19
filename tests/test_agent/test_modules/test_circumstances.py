import pytest
from src.agent.context import PipelineContext
from src.agent.modules.prellm.circumstances import CircumstancesModule


class TestCircumstancesModule:
    def setup_method(self):
        self._module = CircumstancesModule()
        CircumstancesModule.update("")

    @pytest.mark.asyncio
    async def test_injects_circumstances(self):
        CircumstancesModule.update("清明节，用户在家思念奶奶。")
        ctx = PipelineContext(user_message="奶奶你好")
        ctx = await self._module.process(ctx)
        assert "清明节" in ctx.circumstances

    @pytest.mark.asyncio
    async def test_empty_when_not_set(self):
        CircumstancesModule.update("")
        ctx = PipelineContext(user_message="hi")
        ctx = await self._module.process(ctx)
        assert ctx.circumstances == ""

    @pytest.mark.asyncio
    async def test_update_overwrites_previous(self):
        CircumstancesModule.update("first")
        CircumstancesModule.update("second")
        ctx = PipelineContext(user_message="hi")
        ctx = await self._module.process(ctx)
        assert ctx.circumstances == "second"
