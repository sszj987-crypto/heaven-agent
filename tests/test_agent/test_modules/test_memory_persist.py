import tempfile
from pathlib import Path
from datetime import date
from unittest.mock import MagicMock
import pytest
from src.agent.context import PipelineContext
from src.agent.modules.postoutput.memory_persist import MemoryPersistModule
from src.soul.profile import SoulProfile


class TestMemoryPersistModule:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._memory_root = Path(self._tmp.name)
        MemoryPersistModule.configure(self._memory_root)

        self._module = MemoryPersistModule()

        # Mock message_manager
        self._mock_messages = MagicMock()
        self._module._set_deps(self._mock_messages)

    def teardown_method(self):
        self._tmp.cleanup()

    @pytest.mark.asyncio
    async def test_writes_daily_file(self):
        profile = SoulProfile()
        profile.dimensions["basic_info"] = "# 基本信息\n## identity\nname: 王奶奶\n## description\n慈祥。"

        ctx = PipelineContext(user_message="奶奶你好")
        ctx.soul_profile = profile
        ctx.response = "乖孩子，奶奶在呢。"

        await self._module.process(ctx)

        today = date.today().isoformat()
        file_path = self._memory_root / f"{today}.md"
        assert file_path.exists()

        content = file_path.read_text()
        assert "王奶奶" in content
        assert "奶奶你好" in content
        assert "乖孩子" in content

    @pytest.mark.asyncio
    async def test_appends_to_existing_file(self):
        profile = SoulProfile()
        profile.dimensions["basic_info"] = "# 基本信息\n## identity\nname: 测试\n## description"

        ctx1 = PipelineContext(user_message="第一条消息")
        ctx1.soul_profile = profile
        ctx1.response = "第一条回复"

        ctx2 = PipelineContext(user_message="第二条消息")
        ctx2.soul_profile = profile
        ctx2.response = "第二条回复"

        await self._module.process(ctx1)
        await self._module.process(ctx2)

        today = date.today().isoformat()
        file_path = self._memory_root / f"{today}.md"
        content = file_path.read_text()
        assert "第一条消息" in content
        assert "第二条消息" in content

    @pytest.mark.asyncio
    async def test_no_soul_profile_fallback(self):
        ctx = PipelineContext(user_message="hello")
        ctx.soul_profile = None
        ctx.response = "reply"

        await self._module.process(ctx)

        today = date.today().isoformat()
        file_path = self._memory_root / f"{today}.md"
        content = file_path.read_text()
        assert "未知" in content
