"""记忆系统单元测试"""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.memory.store import MemoryStore
from src.memory.sync import (
    MemorySynchronizer,
    _parse_life_experiences,
    _parse_emotional_anchors,
    _parse_relationships,
    _parse_hobbies,
    _parse_special_habits,
    _parse_knowledge_domain,
    MEMORY_DIMENSIONS,
    SOUL_ONLY_DIMENSIONS,
)
from src.soul.loader import SoulLoader


# ── helpers ──────────────────────────────────────────────

def _make_store() -> MemoryStore:
    tmp = tempfile.mkdtemp()
    return MemoryStore(Path(tmp))


def _make_loader(dimensions: dict[str, str] | None = None) -> SoulLoader:
    tmp = tempfile.mkdtemp()
    soul_path = Path(tmp)
    loader = SoulLoader(soul_path)
    from src.soul.profile import DIMENSION_NAMES
    for dim in DIMENSION_NAMES:
        content = (dimensions or {}).get(dim, "")
        if content:
            loader.save_dimension(dim, content)
    return loader


# ── 测试 MemoryStore ─────────────────────────────────────

class TestMemoryStore:
    def test_add_and_search(self):
        store = _make_store()
        store.add("hobbies", "喜欢打游戏，尤其是Dota和CS", {"name": "打游戏"})
        store.add("hobbies", "热爱写代码，用AI辅助开发小程序", {"name": "写代码"})
        store.add("life_experiences", "2020年从华为离职", {"year": "2020"})

        assert store.count == 3

        results = store.search("编程开发")
        assert len(results) >= 1
        assert "写代码" in results[0]["document"]

    def test_search_with_dimension_filter(self):
        store = _make_store()
        store.add("hobbies", "打游戏", {"name": "Dota"})
        store.add("life_experiences", "2020年离职", {"year": "2020"})

        results = store.search("离职", dimensions=["hobbies"])
        # 过滤掉了 life_experiences，但搜索语义相关可能有 hobby 结果
        for r in results:
            assert r["metadata"]["dimension"] == "hobbies"

    def test_empty_store_returns_empty(self):
        store = _make_store()
        assert store.search("test") == []

    def test_get_by_dimension(self):
        store = _make_store()
        store.add("hobbies", "打游戏", {"name": "Dota"})
        store.add("hobbies", "写代码", {"name": "Code"})

        entries = store.get_by_dimension("hobbies")
        assert len(entries) == 2

    def test_delete_by_dimension(self):
        store = _make_store()
        store.add("hobbies", "打游戏")
        store.add("life_experiences", "2020年离职")

        deleted = store.delete_by_dimension("hobbies")
        assert deleted == 1
        assert store.get_by_dimension("hobbies") == []
        assert len(store.get_by_dimension("life_experiences")) == 1

    def test_upsert_dimension(self):
        store = _make_store()
        store.add("hobbies", "old content")

        store.upsert_dimension("hobbies", [
            {"content": "打游戏", "name": "Dota"},
            {"content": "写代码", "name": "Code"},
        ])
        entries = store.get_by_dimension("hobbies")
        assert len(entries) == 2

    def test_stats(self):
        store = _make_store()
        store.add("hobbies", "打游戏")
        store.add("hobbies", "写代码")
        store.add("life_experiences", "2020年离职")

        stats = store.stats()
        assert stats["total"] == 3
        assert stats["by_dimension"]["hobbies"] == 2
        assert stats["by_dimension"]["life_experiences"] == 1

    # ── 遗忘 / 时间衰减测试 ──────────────────────────

    def test_add_includes_strength_metadata(self):
        """add() 自动写入 strength / last_accessed_at / access_count"""
        store = _make_store()
        store.add("hobbies", "打游戏", {"name": "Dota"})

        entries = store.get_by_dimension("hobbies")
        assert len(entries) == 1
        meta = entries[0]["metadata"]
        assert meta["strength"] == 1.0
        assert meta["last_accessed_at"]  # 非空 ISO 字符串
        assert meta["access_count"] == 0
        # 用户自定义 metadata 保留
        assert meta["name"] == "Dota"

    def test_search_result_has_strength_and_combined(self):
        """search 结果携带 strength 和 combined 字段"""
        store = _make_store()
        store.add("hobbies", "打游戏")

        results = store.search("游戏")
        assert len(results) == 1
        assert "strength" in results[0]
        assert "combined" in results[0]
        assert results[0]["strength"] > 0
        assert results[0]["combined"] > 0

    def test_recent_memory_ranks_higher_than_old(self):
        """语义相同的两条记忆，最近访问的排前面"""
        from datetime import timedelta

        store = _make_store()
        # 添加一条新记忆（strength=1.0, last_accessed_at=now）
        store.add("hobbies", "喜欢打游戏，尤其是Dota和CS")

        # 手动注入一条语义相似但很久前的记忆
        old_time = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
        store._collection.add(
            ids=["mem_fake_old"],
            embeddings=[store._embedder.encode_single("以前爱玩游戏")],
            documents=["以前爱玩游戏"],
            metadatas=[{
                "dimension": "hobbies",
                "strength": 1.0,
                "last_accessed_at": old_time,
                "access_count": 0,
            }],
        )

        results = store.search("游戏")
        # 新记忆（strength≈1.0）应排在旧记忆（已衰减）前面
        assert len(results) >= 2
        # 第一条应是新添加的（strength 更高）
        assert "Dota" in results[0]["document"]

    def test_search_boosts_retrieved_memories(self):
        """search 后命中记忆的 access_count 和 last_accessed_at 会更新"""
        store = _make_store()
        store.add("hobbies", "打游戏，喜欢Dota")

        # 首次检索
        results = store.search("Dota")
        assert len(results) == 1

        # 再查一次，检查 metadata 是否更新
        entries = store.get_by_dimension("hobbies")
        assert len(entries) == 1
        meta = entries[0]["metadata"]
        # access_count 至少为 1（被 search 命中过）
        assert meta["access_count"] >= 1

    def test_backward_compatible_no_strength_field(self):
        """没有 strength / last_accessed_at 的旧数据可正常检索"""
        store = _make_store()
        # 模拟旧格式数据（无 strength 等字段）
        store._collection.add(
            ids=["mem_old_style"],
            embeddings=[store._embedder.encode_single("旧格式记忆")],
            documents=["旧格式记忆"],
            metadatas=[{"dimension": "hobbies"}],
        )

        results = store.search("旧格式")
        assert len(results) == 1
        assert results[0]["document"] == "旧格式记忆"
        # 应有默认 strength≈1.0（无时间戳视为刚创建）
        assert results[0]["strength"] > 0.9

    def test_combined_score_equals_similarity_times_strength(self):
        """combined = (1 - distance) × effective_strength"""
        store = _make_store()
        store.add("hobbies", "打游戏，Dota和CS")  # strength=1.0

        results = store.search("打游戏")
        assert len(results) == 1
        similarity = 1.0 - results[0]["distance"]
        expected = similarity * results[0]["strength"]
        assert abs(results[0]["combined"] - expected) < 0.001


# ── 测试解析器 ────────────────────────────────────────────

class TestParseLifeExperiences:
    def test_parses_year_events(self):
        text = "重要事件:\n  - 1995年 出生在湖南\n  - 2020年 从华为离职"
        entries = _parse_life_experiences(text)
        assert len(entries) == 2
        assert entries[0]["year"] == "1995"
        assert "湖南" in entries[0]["content"]

    def test_empty_text(self):
        assert _parse_life_experiences("") == []


class TestParseEmotionalAnchors:
    def test_parses_emotion_entries(self):
        text = (
            "- 类型: 最骄傲的时刻\n"
            "  描述: 高中数学考试拿了满分\n"
            "  情绪: 骄傲\n"
            "- 类型: 挫败\n"
            "  描述: 追求失败\n"
            "  情绪: 伤心\n"
        )
        entries = _parse_emotional_anchors(text)
        assert len(entries) == 2
        assert entries[0]["emotion"] == "骄傲"
        assert "满分" in entries[0]["content"]


class TestParseRelationships:
    def test_parses_relationships(self):
        text = "- 张三: 父亲, 老爸, 严格\n- 李四: 女友, 宝贝"
        entries = _parse_relationships(text)
        assert len(entries) == 2
        assert entries[0]["name"] == "张三"
        assert entries[0]["relation"] == "父亲"


class TestParseHobbies:
    def test_parses_hobbies(self):
        text = "- 打游戏: Dota, CS\n- 写代码: 开发小程序"
        entries = _parse_hobbies(text)
        assert len(entries) == 2
        assert entries[0]["name"] == "打游戏"


class TestParseSpecialHabits:
    def test_parses_habits(self):
        text = "- 喜欢加哈哈结尾\n- 爱吃辣"
        entries = _parse_special_habits(text)
        assert len(entries) == 2
        assert "哈哈" in entries[0]["content"]


class TestParseKnowledgeDomain:
    def test_parses_domains(self):
        text = (
            "擅长领域:\n"
            "- 软件开发: 精通后端\n"
            "不擅长领域:\n"
            "- 投资理财: 经常亏损\n"
        )
        entries = _parse_knowledge_domain(text)
        assert len(entries) == 2
        assert entries[0]["category"] == "擅长领域"


# ── 测试 MemorySynchronizer ─────────────────────────────

class TestMemorySynchronizer:
    def test_sync_dimension(self):
        loader = _make_loader({
            "hobbies": "# 爱好\n爱好列表:\n  - 打游戏: Dota\n  - 写代码: 小程序"
        })
        store = _make_store()
        syncer = MemorySynchronizer(store, loader)

        count = syncer.sync_dimension("hobbies")
        assert count == 2
        assert store.count == 2

    def test_sync_empty_dimension(self):
        loader = _make_loader()
        store = _make_store()
        syncer = MemorySynchronizer(store, loader)

        count = syncer.sync_dimension("hobbies")
        assert count == 0

    def test_sync_soul_only_dimension_skips(self):
        loader = _make_loader({"personality": "# 性格\n- 乐观"})
        store = _make_store()
        syncer = MemorySynchronizer(store, loader)

        count = syncer.sync_dimension("personality")
        assert count == 0

    def test_sync_all(self):
        loader = _make_loader({
            "hobbies": "# 爱好\n- 打游戏: Dota",
            "life_experiences": "# 经历\n- 1995年 出生",
            "personality": "# 性格\n- 乐观",  # soul only, should skip
        })
        store = _make_store()
        syncer = MemorySynchronizer(store, loader)

        results = syncer.sync_all()
        assert results["hobbies"] == 1
        assert results["life_experiences"] == 1

    def test_summarize_dimension(self):
        loader = _make_loader({
            "hobbies": "# 爱好\n- 打游戏: Dota\n- 写代码: 小程序\n- 健身"
        })
        store = _make_store()
        syncer = MemorySynchronizer(store, loader)
        syncer.sync_dimension("hobbies")

        summary = syncer.summarize_dimension("hobbies")
        assert "爱好" in summary
        assert "打游戏" in summary

    def test_summarize_empty_dimension(self):
        loader = _make_loader()
        store = _make_store()
        syncer = MemorySynchronizer(store, loader)

        assert syncer.summarize_dimension("hobbies") == ""


# ── 测试维度分类 ──────────────────────────────────────────

class TestDimensionClassification:
    def test_memory_dimensions_count(self):
        """6 个维度属于记忆系统"""
        assert len(MEMORY_DIMENSIONS) == 6
        assert "life_experiences" in MEMORY_DIMENSIONS
        assert "emotional_anchors" in MEMORY_DIMENSIONS

    def test_soul_only_dimensions_count(self):
        """4 个维度保留在 soul"""
        assert len(SOUL_ONLY_DIMENSIONS) == 4
        assert "personality" in SOUL_ONLY_DIMENSIONS
        assert "linguistic_fingerprint" in SOUL_ONLY_DIMENSIONS

    def test_no_overlap(self):
        assert MEMORY_DIMENSIONS.isdisjoint(SOUL_ONLY_DIMENSIONS)

    def test_all_dimensions_covered(self):
        from src.soul.profile import DIMENSION_NAMES
        covered = MEMORY_DIMENSIONS | SOUL_ONLY_DIMENSIONS
        assert set(DIMENSION_NAMES) == covered
