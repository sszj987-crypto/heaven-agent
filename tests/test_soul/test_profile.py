from src.soul.profile import SoulProfile, DIMENSION_NAMES


class TestSoulProfile:
    def test_empty_profile(self):
        p = SoulProfile()
        assert p.get("basic_info") == ""
        assert p.name == "未知"
        assert not p.has_content

    def test_name_extraction(self):
        p = SoulProfile()
        p.dimensions["basic_info"] = "# 基本信息\n## identity\n姓名: 王奶奶\n## description"
        assert p.name == "王奶奶"

    def test_name_no_basic_info(self):
        p = SoulProfile()
        p.dimensions["personality"] = "some content"
        assert p.name == "未知"

    def test_get_existing_dimension(self):
        p = SoulProfile()
        p.dimensions["hobbies"] = "钓鱼"
        assert p.get("hobbies") == "钓鱼"

    def test_get_missing_dimension_returns_empty(self):
        p = SoulProfile()
        assert p.get("nonexistent") == ""

    def test_has_content_when_dimensions_filled(self):
        p = SoulProfile()
        p.dimensions["basic_info"] = "test"
        assert p.has_content

    def test_has_content_false_for_empty_strings(self):
        p = SoulProfile()
        p.dimensions["basic_info"] = ""
        assert not p.has_content

    def test_has_content_false_for_whitespace(self):
        p = SoulProfile()
        p.dimensions["basic_info"] = "   "
        assert not p.has_content

    def test_dimension_names_count(self):
        assert len(DIMENSION_NAMES) == 6
        assert "basic_info" in DIMENSION_NAMES
        assert "personal_traits" in DIMENSION_NAMES
