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
        # user message 应包含所有 6 个维度
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
            {"personality": "- 乐观开朗", "personal_traits": "- 口头禅: 哈哈"},
            "发现性格开朗"
        )
        dims, summary = distiller._parse_response(response)

        assert dims["personality"] == "- 乐观开朗"
        assert dims["personal_traits"] == "- 口头禅: 哈哈"
        assert summary == "发现性格开朗"

    def test_unchanged_dimensions_filtered_out(self):
        loader = _make_soul_loader()
        distiller = SoulDistiller(_make_llm_client("{}"), loader)

        response = _valid_llm_response(
            {"personality": "UNCHANGED", "personal_traits": "- 读书"}
        )
        dims, _ = distiller._parse_response(response)

        assert "personality" not in dims
        assert "personal_traits" in dims

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
    async def test_distill_with_chat_name(self):
        """distill() 接受 chat_name 参数并传递给 ChatPreprocessor"""
        llm = _make_llm_client(_valid_llm_response({
            "personality": "- 乐观",
        }))
        loader = _make_soul_loader({"basic_info": "姓名: 赵六"})
        distiller = SoulDistiller(llm, loader)

        # chat_name 提供但聊天记录中发言人为"我"，应触发 fallback
        chat = "用户: 哈哈你好搞笑\n逝者: 那可不~"
        result = await distiller.distill(chat, chat_name="赵六")

        assert "personality" in result.changes

    @pytest.mark.asyncio
    async def test_distill_without_chat_name(self):
        """distill() 不传 chat_name 时使用 profile.name"""
        llm = _make_llm_client(_valid_llm_response({
            "personality": "- 乐观",
        }))
        loader = _make_soul_loader({"basic_info": "姓名: 赵六"})
        distiller = SoulDistiller(llm, loader)

        result = await distiller.distill("用户: 哈哈\n逝者: 嘿嘿")

        assert "personality" in result.changes

    @pytest.mark.asyncio
    async def test_parse_failure_raises(self):
        llm = _make_llm_client("这不是有效的 JSON 响应！")
        loader = _make_soul_loader({"basic_info": "姓名: test"})
        distiller = SoulDistiller(llm, loader)

        with pytest.raises(RuntimeError, match="解析失败"):
            await distiller.distill("测试聊天记录")

# ── 测试 _save_changes ─────────────────────────────────────

class TestSaveChanges:
    def test_saves_only_changed_dimensions(self):
        loader = _make_soul_loader({"basic_info": "姓名: 张三", "personality": "- 内向"})
        distiller = SoulDistiller(_make_llm_client("{}"), loader)
        profile = loader.load()

        changes = distiller._save_changes(profile, {
            "personality": "- 外向",  # 变化了
            "basic_info": "姓名: 张三",  # 没变
            "personal_traits": "- 读书",  # 新增
        })

        assert "personality" in changes
        assert "personal_traits" in changes
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
