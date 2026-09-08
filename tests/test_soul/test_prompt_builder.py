from src.soul.profile import SoulProfile
from src.soul.prompt_builder import SoulPromptBuilder


class TestSoulPromptBuilder:
    def setup_method(self):
        self._builder = SoulPromptBuilder()
        self._profile = SoulProfile()
        self._profile.dimensions["basic_info"] = "# 基本信息\n## identity\n姓名: 王奶奶\n## description\n慈祥的退休教师。"
        self._profile.dimensions["personality"] = "# 性格\n## identity\n## description\n温和、善良、有耐心。"
        self._profile.dimensions["life_experiences"] = "# 人生经历\n## identity\n## description\n教了40年书。"
        self._profile.dimensions["relationships"] = "# 人际关系\n## identity\n## description\n有两个孙子。"
        self._profile.dimensions["personal_traits"] = "# 个人特质\n## identity\n## description\n养花、做菜、早起散步。"
        self._profile.dimensions["emotional_anchors"] = "# 情感锚点\n## identity\n## description\n孙子的笑声。"

    def test_build_contains_name(self):
        prompt = self._builder.build(self._profile, "用户正在思念奶奶。")
        assert "王奶奶" in prompt

    def test_build_contains_circumstances(self):
        prompt = self._builder.build(self._profile, "清明节，用户在家。")
        assert "清明节" in prompt

    def test_build_contains_heaven_rules(self):
        prompt = self._builder.build(self._profile, "")
        assert "人物模拟" in prompt
        assert "你不是AI" not in prompt
        assert "绝不声称自己是真实逝者" in prompt
        assert "数字纪念体验" in prompt

    def test_build_contains_dimension_content(self):
        prompt = self._builder.build(self._profile, "")
        assert "慈祥的退休教师" in prompt
        assert "温和、善良" in prompt
        assert "养花、做菜" in prompt

    def test_strip_title_removes_h1(self):
        result = self._builder._strip_title("# 标题\n\n正文内容")
        assert result == "正文内容"
        assert "# 标题" not in result

    def test_strip_title_keeps_h2(self):
        result = self._builder._strip_title("# 标题\n## identity\n姓名: test\n## description\n描述。")
        assert "## identity" in result
        assert "## description" in result

    def test_strip_title_empty_returns_placeholder(self):
        assert self._builder._strip_title("") == "暂无"

    def test_strip_title_none_returns_placeholder(self):
        assert self._builder._strip_title(None) == "暂无"

    def test_build_with_empty_dimensions(self):
        empty = SoulProfile()
        prompt = self._builder.build(empty, "")
        # 应不抛出异常
        assert len(prompt) > 0

    def test_unknown_facts_require_uncertainty_instead_of_invention(self):
        prompt = self._builder.build(self._profile, "")

        assert "资料没有明确提供" in prompt
        assert "不要编造" in prompt

    def test_conflicting_facts_must_be_surfaced_without_guessing(self):
        prompt = self._builder.build(self._profile, "")

        assert "资料互相冲突" in prompt
        assert "不要擅自选择" in prompt

    def test_reply_contract_requests_tts_instruction(self):
        prompt = self._builder.build(self._profile, "")

        assert '"instruct"' in prompt
        assert "语气" in prompt
