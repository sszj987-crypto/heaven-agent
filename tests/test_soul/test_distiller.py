"""灵魂档案蒸馏器单元测试"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.soul.distiller import (
    SoulDistiller,
    DistillResult,
    _strip_markdown_fence,
    CHUNK_SIZE_BYTES,
    DIMENSION_LABELS,
)
from src.soul.loader import SoulLoader
from src.soul.profile import DIMENSION_NAMES


# ── helpers ──────────────────────────────────────────────

def _make_llm_client(response_text: str):
    """创建一个返回固定响应的 mock LLM 客户端"""
    mock = MagicMock()
    mock.model = "test-model"
    mock.chat = AsyncMock(return_value=response_text)
    return mock


def _make_soul_loader(dimensions: dict[str, str] | None = None):
    """创建一个 SoulLoader，指向临时目录"""
    tmp = tempfile.mkdtemp()
    soul_path = Path(tmp)
    loader = SoulLoader(soul_path)
    # 写入初始维度内容
    for dim in DIMENSION_NAMES:
        content = (dimensions or {}).get(dim, "")
        if content:
            loader.save_dimension(dim, content)
    return loader


def _valid_llm_response(dimensions: dict[str, str], summary: str = "测试摘要") -> str:
    """构建合法的 LLM 响应 JSON"""
    return json.dumps({
        "dimensions": dimensions,
        "summary": summary,
    }, ensure_ascii=False)


# ── 测试 _strip_markdown_fence ──────────────────────────────

class TestStripMarkdownFence:
    def test_no_fence(self):
        assert _strip_markdown_fence('{"hello": "world"}') == '{"hello": "world"}'

    def test_with_complete_fence(self):
        text = '```json\n{"hello": "world"}\n```'
        assert _strip_markdown_fence(text) == '{"hello": "world"}'

    def test_with_partial_fence(self):
        text = '```\n{"hello": "world"}'
        assert _strip_markdown_fence(text) == '{"hello": "world"}'


# ── 测试 DistillResult ─────────────────────────────────────

class TestDistillResult:
    def test_defaults(self):
        r = DistillResult()
        assert r.changes == []
        assert r.profile == {}
        assert r.summary == ""

    def test_with_data(self):
        r = DistillResult(
            changes=["personality"],
            profile={"personality": "乐观"},
            summary="发现了性格特征",
        )
        assert len(r.changes) == 1
        assert r.profile["personality"] == "乐观"


# ── 测试 _build_messages ────────────────────────────────────

class TestBuildMessages:
    def test_includes_all_dimensions(self):
        loader = _make_soul_loader({"basic_info": "姓名: 张三"})
        profile = loader.load()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        messages = distiller._build_messages(profile, "你好")

        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # user message 应包含所有 10 个维度
        for dim in DIMENSION_NAMES:
            assert dim in messages[1]["content"]

    def test_includes_chat_text(self):
        loader = _make_soul_loader()
        profile = loader.load()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        chat = "用户: 你好\n逝者: 嗨！"
        messages = distiller._build_messages(profile, chat)

        assert chat in messages[1]["content"]

    def test_empty_dimension_shows_placeholder(self):
        loader = _make_soul_loader()
        profile = loader.load()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        messages = distiller._build_messages(profile, "test")

        assert "暂无内容" in messages[1]["content"]


# ── 测试 _parse_response ────────────────────────────────────

class TestParseResponse:
    def test_valid_response(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        response = _valid_llm_response(
            {"personality": "- 乐观开朗", "linguistic_fingerprint": "- 口头禅: 哈哈"},
            "发现性格开朗"
        )
        dims, summary = distiller._parse_response(response)

        assert dims["personality"] == "- 乐观开朗"
        assert dims["linguistic_fingerprint"] == "- 口头禅: 哈哈"
        assert summary == "发现性格开朗"

    def test_unchanged_dimensions_filtered_out(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        response = _valid_llm_response(
            {"personality": "UNCHANGED", "hobbies": "- 读书"}
        )
        dims, _ = distiller._parse_response(response)

        assert "personality" not in dims
        assert "hobbies" in dims

    def test_empty_string_treated_as_unchanged(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        response = _valid_llm_response({"personality": ""})
        dims, _ = distiller._parse_response(response)

        assert "personality" not in dims

    def test_removes_markdown_fence(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        response = _valid_llm_response({"personality": "test"})
        fenced = "```json\n" + response + "\n```"
        dims, _ = distiller._parse_response(fenced)

        assert dims["personality"] == "test"

    def test_invalid_json_raises(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        with pytest.raises(Exception):
            distiller._parse_response("not valid json at all")

    def test_missing_dimensions_key_returns_empty(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        dims, summary = distiller._parse_response('{"summary": "no dims"}')
        assert dims == {}
        assert summary == "no dims"

    def test_invalid_dimension_names_ignored(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        response = _valid_llm_response({"fake_dimension": "content"})
        dims, _ = distiller._parse_response(response)

        assert "fake_dimension" not in dims


# ── 测试 _format_current_profile ────────────────────────────

class TestFormatCurrentProfile:
    def test_includes_all_dimensions(self):
        loader = _make_soul_loader({"basic_info": "姓名: 李四"})
        profile = loader.load()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        formatted = distiller._format_current_profile(profile)

        for dim in DIMENSION_NAMES:
            label = DIMENSION_LABELS[dim]
            assert label in formatted
            assert dim in formatted

    def test_empty_dimension_shows_placeholder(self):
        loader = _make_soul_loader()
        profile = loader.load()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        formatted = distiller._format_current_profile(profile)

        assert "暂无内容" in formatted


# ── 测试 distill 主流程 ─────────────────────────────────────

class TestDistill:
    @pytest.mark.asyncio
    async def test_empty_chat_raises(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        with pytest.raises(ValueError, match="为空"):
            await distiller.distill("  ")

    @pytest.mark.asyncio
    async def test_oversized_chat_is_chunked(self):
        """大文件自动切分多段处理，不再报错"""
        llm = _make_llm_client(_valid_llm_response({
            "personality": "- 乐观", "hobbies": "- 读书"
        }))
        loader = _make_soul_loader()
        distiller = SoulDistiller(llm, loader)

        # 构造超过 chunk_size 的文本（每个中文字符 3 bytes → 需要 > chunk_size / 3 字符）
        oversized = "你好啊！" * (CHUNK_SIZE_BYTES // 3 + 100)
        result = await distiller.distill(oversized)

        # 应该被切分为多段并成功处理
        assert result.changes
        assert llm.chat.call_count >= 2  # 至少调用了两次 LLM

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        llm = _make_llm_client("{}")
        llm.chat.side_effect = RuntimeError("API error")

        loader = _make_soul_loader()
        distiller = SoulDistiller(llm, loader)

        with pytest.raises(RuntimeError, match="LLM 调用失败"):
            await distiller.distill("测试聊天记录")

    @pytest.mark.asyncio
    async def test_no_changes_when_all_unchanged(self):
        llm = _make_llm_client(_valid_llm_response({
            dim: "UNCHANGED" for dim in DIMENSION_NAMES
        }))
        loader = _make_soul_loader({"basic_info": "姓名: 王五"})
        distiller = SoulDistiller(llm, loader)

        result = await distiller.distill("测试聊天记录")
        assert result.changes == []

    @pytest.mark.asyncio
    async def test_updates_changed_dimensions(self):
        new_personality = "- 乐观开朗\n- 幽默风趣"
        llm = _make_llm_client(_valid_llm_response({
            "personality": new_personality,
        }))
        loader = _make_soul_loader({"basic_info": "姓名: 赵六"})
        distiller = SoulDistiller(llm, loader)

        result = await distiller.distill("用户: 哈哈你好搞笑\n逝者: 那可不~")

        assert "personality" in result.changes
        assert result.profile["personality"] == new_personality
        assert result.summary

    @pytest.mark.asyncio
    async def test_cold_start_with_empty_profile(self):
        """空档案冷启动：LLM 根据聊天记录生成初始内容"""
        llm = _make_llm_client(_valid_llm_response({
            "basic_info": "姓名: 张三",
            "personality": "- 乐观",
        }, "从零构建了基本档案"))
        loader = _make_soul_loader()  # 全空
        distiller = SoulDistiller(llm, loader)

        result = await distiller.distill("用户: 张三你说得对\n逝者: 哈哈谢谢")

        assert "basic_info" in result.changes
        assert "personality" in result.changes
        assert result.summary == "从零构建了基本档案"

    @pytest.mark.asyncio
    async def test_parse_failure_raises(self):
        llm = _make_llm_client("这不是有效的 JSON 响应！")
        loader = _make_soul_loader({"basic_info": "姓名: test"})
        distiller = SoulDistiller(llm, loader)

        with pytest.raises(RuntimeError, match="解析失败"):
            await distiller.distill("测试聊天记录")

    @pytest.mark.asyncio
    async def test_chunked_processing_accumulates_changes(self):
        """分段处理时，后一段的 LLM 能看到前一段的累积档案"""
        call_count = [0]
        def _sequential_response(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _valid_llm_response({"personality": "- 乐观"}, "第一段: 发现性格")
            else:
                return _valid_llm_response({"hobbies": "- 读书"}, "第二段: 发现爱好")

        llm = _make_llm_client("")
        llm.chat = AsyncMock(side_effect=_sequential_response)

        loader = _make_soul_loader()
        distiller = SoulDistiller(llm, loader)

        oversized = "你好！\n\n" * (CHUNK_SIZE_BYTES // 3 + 150)
        result = await distiller.distill(oversized)

        assert "personality" in result.changes
        assert "hobbies" in result.changes
        assert llm.chat.call_count >= 2
        assert "第一段" in result.summary
        assert "第二段" in result.summary


# ── 测试 _split_chunks ──────────────────────────────────────

class TestSplitChunks:
    def test_small_text_returns_single_chunk(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        chunks = distiller._split_chunks("短文本")
        assert len(chunks) == 1
        assert chunks[0] == "短文本"

    def test_large_text_splits_at_double_newline(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        # 构建约 2.5MB 的文本，确保触发切分（> 800KB * 1.2 ≈ 960KB）
        msg = "哈" * 300  # ~900 bytes
        big_text = (msg + "\n\n" + msg + "\n\n") * 1500
        chunks = distiller._split_chunks(big_text)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) > 0

    def test_no_double_newline_falls_back(self):
        """不足 chunk_size * 1.2 的文本不触发切分"""
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        # CHUNK_SIZE_BYTES / 3 字节 ≈ chunk_size，小于 chunk_size * 1.2 不触发切分
        big_text = "哈" * (CHUNK_SIZE_BYTES // 3)
        chunks = distiller._split_chunks(big_text)
        assert len(chunks) == 1
        assert chunks[0] == big_text


# ── 测试 _save_changes ─────────────────────────────────────

class TestSaveChanges:
    def test_saves_only_changed_dimensions(self):
        loader = _make_soul_loader({"basic_info": "姓名: 张三", "personality": "- 内向"})
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        profile = loader.load()

        changes = distiller._save_changes(profile, {
            "personality": "- 外向",  # 变化了
            "basic_info": "姓名: 张三",  # 没变
            "hobbies": "- 读书",  # 新增
        })

        assert "personality" in changes
        assert "hobbies" in changes
        assert "basic_info" not in changes

    def test_returns_empty_when_no_changes(self):
        loader = _make_soul_loader({"basic_info": "姓名: 张三"})
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        profile = loader.load()

        changes = distiller._save_changes(profile, {"basic_info": "姓名: 张三"})
        assert changes == []


# ── 测试 _merge_profile ────────────────────────────────────

class TestMergeProfile:
    def test_new_overrides_old(self):
        loader = _make_soul_loader({"basic_info": "姓名: 旧名"})
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        profile = loader.load()

        merged = distiller._merge_profile(profile, {"basic_info": "姓名: 新名"})
        assert merged["basic_info"] == "姓名: 新名"

    def test_unchanged_dimensions_keep_old_value(self):
        loader = _make_soul_loader({"personality": "- 内向"})
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        profile = loader.load()

        merged = distiller._merge_profile(profile, {})
        assert merged["personality"] == "- 内向"
