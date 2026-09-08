import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from src.soul.loader import SoulLoader
from src.soul.profile import DIMENSION_NAMES


class TestSoulLoader:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._soul_path = Path(self._tmp.name)
        self._loader = SoulLoader(self._soul_path)

        # 创建几个维度文件
        (self._soul_path / "basic_info.md").write_text(
            "# 基本信息\n## identity\n姓名: 王奶奶\n## description\n慈祥的老人。"
        )
        (self._soul_path / "personality.md").write_text(
            "# 性格\n## identity\n## description\n温和善良。"
        )

    def teardown_method(self):
        self._tmp.cleanup()

    def test_load_full_profile(self):
        profile = self._loader.load()
        assert profile.name == "王奶奶"
        assert "慈祥" in profile.get("basic_info")
        assert "温和善良" in profile.get("personality")

    def test_load_missing_dimension_returns_empty(self):
        profile = self._loader.load()
        assert profile.get("hobbies") == ""

    def test_load_all_10_dimensions_exist_in_profile(self):
        profile = self._loader.load()
        for dim in DIMENSION_NAMES:
            assert dim in profile.dimensions

    def test_load_dimension(self):
        content = self._loader.load_dimension("basic_info")
        assert "王奶奶" in content

    def test_load_nonexistent_dimension(self):
        content = self._loader.load_dimension("nonexistent")
        assert content == ""

    def test_save_dimension_creates_file(self):
        self._loader.save_dimension("hobbies", "# 爱好\n## identity\n## description\n钓鱼、养花。")

        file_path = self._soul_path / "hobbies.md"
        assert file_path.exists()
        content = file_path.read_text()
        assert "钓鱼、养花" in content

    def test_save_dimension_overwrites(self):
        self._loader.save_dimension("basic_info", "new content")
        content = self._loader.load_dimension("basic_info")
        assert content == "new content"

    def test_failed_atomic_replace_preserves_previous_dimension(self):
        original = self._loader.load_dimension("basic_info")

        with patch("src.data.files.os.replace", side_effect=OSError("disk failure")):
            with pytest.raises(OSError, match="disk failure"):
                self._loader.save_dimension("basic_info", "partial new content")

        assert self._loader.load_dimension("basic_info") == original

    def test_save_creates_directory_if_not_exists(self):
        new_path = self._soul_path / "new_soul"
        loader = SoulLoader(new_path)
        loader.save_dimension("basic_info", "test")
        assert new_path.is_dir()
        assert (new_path / "basic_info.md").exists()

    def test_load_nonexistent_soul_raises(self):
        loader = SoulLoader(self._soul_path / "does_not_exist")
        try:
            loader.load()
            assert False, "Should have raised"
        except FileNotFoundError:
            pass


# ── Skill Card 标记/解析测试 ────────────────────────────

from src.soul.loader import _escape_markdown_headers, _unescape_markdown_headers
from src.soul.skill_card import SkillCard


class TestEscapeMarkdownHeaders:
    def test_escapes_leading_double_hash(self):
        content = "## 沈志坚的扮演指令\n\n你是沈志坚"
        escaped = _escape_markdown_headers(content)
        lines = escaped.split("\n")
        assert lines[0] == "\\## 沈志坚的扮演指令"

    def test_no_escape_for_triple_hash(self):
        content = "### 表达基因：你怎么说话\n- 短句优先"
        escaped = _escape_markdown_headers(content)
        assert escaped == content  # ### 不需要转义

    def test_no_escape_midline_hash(self):
        content = "这不是标题 ## 只是文字"
        escaped = _escape_markdown_headers(content)
        assert escaped == content

    def test_roundtrip(self):
        content = "## 沈志坚的扮演指令\n\n### 表达基因\n短句优先\n\n## 决策启发式"
        escaped = _escape_markdown_headers(content)
        restored = _unescape_markdown_headers(escaped)
        assert restored == content


class TestSkillCardRoundtrip:
    """验证 SkillCard save → load 完整循环，特别是 ## 转义"""

    def test_roundtrip_with_hash_headers_in_content(self):
        """核心测试：内容中含 ## 开头的行，save/load 后不丢失"""
        tmp = tempfile.TemporaryDirectory()
        loader = SoulLoader(Path(tmp.name))

        skill = SkillCard(
            role_playing_rules="## 扮演指令\n\n你是张三\n\n### 表达基因\n短句优先",
            expression_dna="## 表达分析\n- 爱用短句\n- 频繁使用问号",
            decision_heuristics="当对方抱怨时 → 自嘲回应",
            mental_models="条件适应性评估",
            values_anti_patterns="情感至上",
            inner_tensions="爱情与金钱的冲突",
        )

        loader.save_skill(skill)
        loaded = loader.load_skill()

        assert loaded is not None
        # 关键：role_playing_rules 中 ## 开头的内容不丢失
        assert "扮演指令" in loaded.role_playing_rules
        assert "你是张三" in loaded.role_playing_rules
        assert "表达基因" in loaded.role_playing_rules
        # expression_dna 也不丢失
        assert "表达分析" in loaded.expression_dna
        assert "爱用短句" in loaded.expression_dna
        # 其他字段完整
        assert loaded.decision_heuristics == "当对方抱怨时 → 自嘲回应"
        assert loaded.mental_models == "条件适应性评估"
        assert loaded.values_anti_patterns == "情感至上"
        assert loaded.inner_tensions == "爱情与金钱的冲突"

        tmp.cleanup()

    def test_roundtrip_empty_sections(self):
        """空 section 不写入文件，加载后保持为空"""
        tmp = tempfile.TemporaryDirectory()
        loader = SoulLoader(Path(tmp.name))

        skill = SkillCard(
            role_playing_rules="## 只有扮演规则",
            expression_dna="",
            decision_heuristics="",
            mental_models="",
            values_anti_patterns="",
            inner_tensions="",
        )

        loader.save_skill(skill)
        loaded = loader.load_skill()

        assert loaded is not None
        assert "只有扮演规则" in loaded.role_playing_rules
        assert loaded.expression_dna == ""
        assert loaded.decision_heuristics == ""

        tmp.cleanup()

    def test_load_nonexistent_skill_returns_none(self):
        tmp = tempfile.TemporaryDirectory()
        loader = SoulLoader(Path(tmp.name))
        assert loader.load_skill() is None
        tmp.cleanup()
