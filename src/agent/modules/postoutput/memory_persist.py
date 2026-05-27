import os
from datetime import date
from pathlib import Path
from ..base import PipelineModule
from ...context import PipelineContext
from ...pipeline import Pipeline

# 默认存储根目录: 项目根目录/memory/daily
DEFAULT_MEMORY_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "memory" / "daily"


@Pipeline.register(slot="postoutput", order=2)
class MemoryPersistModule(PipelineModule):
    """
    记忆落盘模块。
    在上下文压缩后，将当日对话追加写入 memory/daily/YYYY-MM-DD.md。
    """

    _memory_root: Path = DEFAULT_MEMORY_ROOT
    _messages = None

    @classmethod
    def set_deps(cls, message_manager):
        cls._messages = message_manager

    @classmethod
    def configure(cls, memory_root: Path):
        """配置存储根目录"""
        cls._memory_root = Path(memory_root)

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        today = date.today().isoformat()  # "YYYY-MM-DD"
        file_path = self._memory_root / f"{today}.md"

        # 构建当日记录
        content = self._format_entry(ctx)
        os.makedirs(self._memory_root, exist_ok=True)

        # 追加写入（文件存在则在末尾追加）
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content)

        return ctx

    def _format_entry(self, ctx: PipelineContext) -> str:
        """格式化一条对话记录"""
        name = ctx.soul_profile.name if ctx.soul_profile else "未知"
        entry = f"## {name}\n"
        entry += f"**用户**: {ctx.user_message}\n\n"
        entry += f"**{name}**: {ctx.response}\n\n"
        entry += "---\n\n"
        return entry
