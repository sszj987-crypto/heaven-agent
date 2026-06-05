from pathlib import Path
from .profile import SoulProfile, DIMENSION_NAMES
from .skill_card import SkillCard, SECTION_HEADERS

_SKILL_FILE = "skill.md"

# 全局懒汉单例
_soul_loader = None  # type: SoulLoader | None


def get_soul_loader():
    """获取全局 SoulLoader 单例（首次调用时自动初始化）"""
    global _soul_loader
    if _soul_loader is None:
        from ..config.settings import Settings
        _soul_loader = SoulLoader(Settings.get().soul_path)
    return _soul_loader


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

    # ── Skill Card I/O ───────────────────────────────────

    def has_skill(self) -> bool:
        """检查 skill.md 是否存在"""
        return (self._soul_path / _SKILL_FILE).exists()

    def load_skill(self) -> SkillCard | None:
        """从 skill.md 加载行为规则卡。不存在则返回 None。"""
        path = self._soul_path / _SKILL_FILE
        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8")
        sections = _parse_skill_markdown(content)
        return SkillCard.from_dict(sections)

    def save_skill(self, skill: SkillCard):
        """保存行为规则卡到 skill.md。"""
        self._soul_path.mkdir(parents=True, exist_ok=True)
        path = self._soul_path / _SKILL_FILE
        path.write_text(_format_skill_markdown(skill), encoding="utf-8")


def _escape_markdown_headers(content: str) -> str:
    """转义内容中以 ##  开头的行（不含 ###），防止被解析为 markdown section header"""
    lines = content.split("\n")
    escaped = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped == "##":
            escaped.append("\\" + line)
        else:
            escaped.append(line)
    return "\n".join(escaped)


def _unescape_markdown_headers(content: str) -> str:
    """还原被转义的 ## 标题"""
    lines = content.split("\n")
    unescaped = []
    for line in lines:
        if line.strip().startswith("\\##"):
            unescaped.append(line.replace("\\##", "##", 1))
        else:
            unescaped.append(line)
    return "\n".join(unescaped)


def _parse_skill_markdown(content: str) -> dict[str, str]:
    """解析 skill.md → {field_name: section_content}。"""
    sections: dict[str, str] = {}
    # 建立中文标题 → 字段名的反向映射
    label_to_field = {v: k for k, v in SECTION_HEADERS.items()}

    current_field: str | None = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            # 保存上一个 section
            if current_field and current_lines:
                sections[current_field] = _unescape_markdown_headers(
                    "\n".join(current_lines).strip())
            current_lines = []
            label = stripped[3:].strip()
            current_field = label_to_field.get(label)
        elif current_field:
            current_lines.append(line)

    # 保存最后一个 section
    if current_field and current_lines:
        sections[current_field] = _unescape_markdown_headers(
            "\n".join(current_lines).strip())

    return sections


def _format_skill_markdown(skill: SkillCard) -> str:
    """将 SkillCard 格式化为 markdown 文件内容。"""
    # 从 basic_info 提取姓名作为标题
    name = "灵魂档案"
    if skill.has_content:
        from .profile import DIMENSION_NAMES
        name = "灵魂"

    lines = [f"# 行为规则卡 - {name}", ""]

    for field, label in SECTION_HEADERS.items():
        content = getattr(skill, field, "").strip()
        if content:
            lines.append(f"## {label}")
            lines.append("")
            lines.append(_escape_markdown_headers(content))
            lines.append("")

    return "\n".join(lines).strip() + "\n"
