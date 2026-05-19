from pathlib import Path
from .profile import SoulProfile, DIMENSION_NAMES


class SoulLoader:
    """从配置的 soul 目录加载灵魂档案的 10 个维度 md 文件"""

    def __init__(self, soul_path: Path):
        self._soul_path = Path(soul_path)

    def load(self) -> SoulProfile:
        """加载完整灵魂档案"""
        if not self._soul_path.is_dir():
            raise FileNotFoundError(f"Soul not found: {self._soul_path}")

        profile = SoulProfile()
        for dim in DIMENSION_NAMES:
            self._load_dimension(profile, dim)
        return profile

    def load_dimension(self, dimension: str) -> str:
        """加载单个维度内容"""
        file_path = self._soul_path / f"{dimension}.md"
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
        return ""

    def save_dimension(self, dimension: str, content: str):
        """保存单个维度内容到 md 文件"""
        self._soul_path.mkdir(parents=True, exist_ok=True)
        file_path = self._soul_path / f"{dimension}.md"
        file_path.write_text(content, encoding="utf-8")

    def _load_dimension(self, profile: SoulProfile, dimension: str):
        file_path = self._soul_path / f"{dimension}.md"
        if file_path.exists():
            profile.dimensions[dimension] = file_path.read_text(encoding="utf-8")
        else:
            profile.dimensions[dimension] = ""
