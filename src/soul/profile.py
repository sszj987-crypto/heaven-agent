from dataclasses import dataclass, field

# 维度文件名列表
DIMENSION_NAMES = [
    "basic_info",
    "personality",
    "life_experiences",
    "relationships",
    "hobbies",
    "special_habits",
    "values_beliefs",
    "emotional_anchors",
    "linguistic_fingerprint",
    "knowledge_domain",
]


@dataclass
class SoulProfile:
    """灵魂档案，包含 10 个维度的 md 内容"""
    dimensions: dict[str, str] = field(default_factory=dict)

    def get(self, dimension: str) -> str:
        return self.dimensions.get(dimension, "")

    @property
    def name(self) -> str:
        """从 basic_info 中提取姓名"""
        content = self.dimensions.get("basic_info", "")
        for line in content.split("\n"):
            if line.startswith("姓名:") or line.startswith("姓名："):
                return line.split(":", 1)[-1].split("：", 1)[-1].strip()
        return "未知"

    @property
    def has_content(self) -> bool:
        """是否有任何维度有内容"""
        return any(v.strip() for v in self.dimensions.values())
