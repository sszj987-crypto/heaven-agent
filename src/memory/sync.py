"""灵魂档案 ↔ 记忆系统 同步器。

将 soul 维度 markdown 解析为独立的记忆条目存入 ChromaDB，
同时在 soul .md 中保留摘要版本。
"""

import re

from .store import MemoryStore
from ..soul.loader import SoulLoader
from ..soul.profile import DIMENSION_NAMES
from ..config.logger import get_logger

log = get_logger("memory")

# 适合迁移到记忆系统的维度（动态积累型）
MEMORY_DIMENSIONS = {
    "life_experiences",
    "emotional_anchors",
    "relationships",
    "hobbies",
    "special_habits",
    "knowledge_domain",
}

# 保留在 soul 的维度（稳定身份）
SOUL_ONLY_DIMENSIONS = {
    "basic_info",
    "personality",
    "linguistic_fingerprint",
    "values_beliefs",
}


class MemorySynchronizer:
    """将 soul 维度的详细内容拆分为记忆条目，同时保持 soul 摘要。"""

    def __init__(self, store: MemoryStore, loader: SoulLoader):
        self._store = store
        self._loader = loader

    # ── Soul → Memory ────────────────────────────────────

    def sync_dimension(self, dimension: str) -> int:
        """将单个维度的 soul markdown 同步到记忆库。返回新增条数。"""
        if dimension not in MEMORY_DIMENSIONS:
            log.debug("维度 %s 不属于记忆维度，跳过", dimension)
            return 0

        content = self._loader.load_dimension(dimension)
        if not content.strip():
            log.debug("维度 %s 无内容，跳过同步", dimension)
            return 0

        entries = _parse_dimension_to_entries(dimension, content)
        if not entries:
            log.debug("维度 %s 解析后无有效条目", dimension)
            return 0

        return self._store.upsert_dimension(dimension, entries)

    def sync_all(self) -> dict[str, int]:
        """将所有记忆维度同步到 ChromaDB。返回 {dimension: count}。"""
        results = {}
        for dim in MEMORY_DIMENSIONS:
            try:
                count = self.sync_dimension(dim)
                results[dim] = count
            except Exception as e:
                log.error("同步维度 %s 失败: %s", dim, e)
                results[dim] = 0
        log.info("全量同步完成: %s", results)
        return results

    # ── Soul 摘要生成 ───────────────────────────────────

    def summarize_dimension(self, dimension: str) -> str:
        """从记忆条目生成 soul 摘要（取前几条的标题部分）。"""
        entries = self._store.get_by_dimension(dimension)
        if not entries:
            return ""

        labels = _DIMENSION_HEADER_LABELS
        title = labels.get(dimension, dimension)
        lines = [f"# {title}", ""]

        # 根据维度类型选择摘要格式
        if dimension == "life_experiences":
            lines.append("重要事件:")
            for e in entries[:8]:
                doc = e["document"].strip()
                line = doc.split("\n")[0] if "\n" in doc else doc[:80]
                lines.append(f"  - {line}")
        elif dimension == "emotional_anchors":
            lines.append("情感记忆:")
            for e in entries[:8]:
                emo = e["metadata"].get("emotion", "")
                doc = e["document"].strip()
                line = doc.split("\n")[0] if "\n" in doc else doc[:80]
                lines.append(f"  - {line}（{emo}）" if emo else f"  - {line}")
        elif dimension == "relationships":
            lines.append("关系列表:")
            for e in entries[:10]:
                name = e["metadata"].get("name", "")
                rel = e["metadata"].get("relation", "")
                doc = e["document"].strip()
                line = doc.split("\n")[0] if "\n" in doc else doc[:80]
                prefix = f"{name}: {rel}" if name else line
                lines.append(f"  - {prefix}")
        elif dimension == "hobbies":
            lines.append("爱好列表:")
            for e in entries[:10]:
                name = e["metadata"].get("name", "")
                lines.append(f"  - {name}" if name else f"  - {e['document'].strip()[:60]}")
        elif dimension == "special_habits":
            lines.append("习惯列表:")
            for e in entries[:8]:
                doc = e["document"].strip()
                line = doc.split("\n")[0] if "\n" in doc else doc[:80]
                lines.append(f"  - {line}")
        elif dimension == "knowledge_domain":
            lines.append("擅长领域:")
            for e in entries[:8]:
                domain = e["metadata"].get("domain", "")
                doc = e["document"].strip()
                line = domain or (doc.split("\n")[0] if "\n" in doc else doc[:80])
                lines.append(f"  - {line}")

        return "\n".join(lines)


# ── 维度 → 条目 解析 ───────────────────────────────────

_DIMENSION_HEADER_LABELS: dict[str, str] = {
    "life_experiences": "人生经历",
    "emotional_anchors": "情感锚点",
    "relationships": "人际关系",
    "hobbies": "爱好",
    "special_habits": "特殊习惯",
    "knowledge_domain": "知识领域",
}


def _parse_dimension_to_entries(dimension: str, content: str) -> list[dict]:
    """将维度 markdown 解析为独立记忆条目列表。"""
    # 去掉第一行 # header
    body = content.strip()
    if body.startswith("#"):
        body = "\n".join(body.split("\n")[1:]).strip()

    parser = _DIMENSION_PARSERS.get(dimension)
    if parser:
        return parser(body)
    return _parse_generic(body)


def _parse_life_experiences(text: str) -> list[dict]:
    """解析人生经历：`- YYYY年 事件描述`"""
    entries = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or not line.startswith("-"):
            continue
        content = line.lstrip("- ").strip()
        if content:
            year_match = re.match(r"(\d{4})\s*年?", content)
            year = year_match.group(1) if year_match else ""
            entries.append({
                "content": content,
                "year": year,
            })
    return entries


def _parse_emotional_anchors(text: str) -> list[dict]:
    """解析情感锚点：按 `- 类型:` 分组"""
    entries = []
    current_type = ""
    current_desc: list[str] = []
    current_emotion = ""

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- 类型:") or stripped.startswith("- 类型："):
            if current_desc:
                entries.append({
                    "content": "\n".join(current_desc),
                    "type": current_type,
                    "emotion": current_emotion,
                })
                current_desc = []
            current_type = stripped.split(":", 1)[-1].strip()
        elif stripped.startswith("描述:") or stripped.startswith("描述："):
            current_desc.append(stripped.split(":", 1)[-1].strip())
        elif stripped.startswith("情绪:") or stripped.startswith("情绪："):
            current_emotion = stripped.split(":", 1)[-1].strip()
            if not current_desc and current_type:
                current_desc.append(current_type)

    if current_desc:
        entries.append({
            "content": "\n".join(current_desc),
            "type": current_type,
            "emotion": current_emotion,
        })
    return entries


def _parse_relationships(text: str) -> list[dict]:
    """解析人际关系：`- 姓名: 关系, 称呼, 备注`"""
    entries = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or not line.startswith("-"):
            continue
        content = line.lstrip("- ").strip()
        if content:
            parts = [p.strip() for p in content.split(",", 2)]
            name_rel = parts[0] if parts else content
            name = name_rel.split(":", 1)[0].strip() if ":" in name_rel else name_rel
            relation = name_rel.split(":", 1)[-1].strip() if ":" in name_rel else ""
            entries.append({
                "content": content,
                "name": name,
                "relation": relation,
            })
    return entries


def _parse_hobbies(text: str) -> list[dict]:
    """解析爱好：`- 名称: 内容 / 备注: xxx`"""
    entries = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or not line.startswith("-"):
            continue
        content = line.lstrip("- ").strip()
        if not content:
            continue
        # 处理 "名称: 写代码" 或 "写代码: 备注" 两种格式
        if ":" in content:
            key, _, val = content.partition(":")
            key, val = key.strip(), val.strip()
            if key == "名称":
                name = val
            else:
                name = key
        else:
            name = content
        entries.append({"content": content, "name": name})
    return entries


def _parse_special_habits(text: str) -> list[dict]:
    """解析特殊习惯：`- 描述`"""
    return _parse_generic_items(text)


def _parse_knowledge_domain(text: str) -> list[dict]:
    """解析知识领域：`擅长领域:` / `不擅长领域:` + `- 领域: 备注`"""
    entries = []
    category = ""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("擅长领域") or line.startswith("不擅长领域"):
            category = line.split(":", 1)[0].strip()
            continue
        if line.startswith("-"):
            content = line.lstrip("- ").strip()
            if content:
                domain = content.split(":")[0].strip() if ":" in content else content
                entries.append({
                    "content": content,
                    "domain": domain,
                    "category": category,
                })
    return entries


def _parse_generic_items(text: str) -> list[dict]:
    """通用列表解析：`- xxx`"""
    entries = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("-"):
            content = line.lstrip("- ").strip()
            if content:
                entries.append({"content": content})
    return entries


def _parse_generic(text: str) -> list[dict]:
    """回退解析：将整段文本作为一个条目"""
    return [{"content": text}]


_DIMENSION_PARSERS = {
    "life_experiences": _parse_life_experiences,
    "emotional_anchors": _parse_emotional_anchors,
    "relationships": _parse_relationships,
    "hobbies": _parse_hobbies,
    "special_habits": _parse_special_habits,
    "knowledge_domain": _parse_knowledge_domain,
}
