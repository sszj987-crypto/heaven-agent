import tempfile
from pathlib import Path
from src.soul.loader import SoulLoader
from src.soul.profile import DIMENSION_NAMES


class TestSoulLoader:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._soul_path = Path(self._tmp.name)
        self._loader = SoulLoader(self._soul_path)

        # 创建几个维度文件
        (self._soul_path / "basic_info.md").write_text(
            "# 基本信息\n## identity\nname: 王奶奶\n## description\n慈祥的老人。"
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
