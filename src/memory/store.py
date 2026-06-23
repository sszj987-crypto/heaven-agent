"""ChromaDB 记忆存储：持久化向量索引 + 元数据过滤 + 时间衰减"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from .embedder import MemoryEmbedder
from ..config.logger import get_logger

log = get_logger("memory")

COLLECTION_NAME = "soul_memories"

# 全局懒汉单例
_memory_store = None  # type: MemoryStore | None


def get_memory_store():
    """获取全局 MemoryStore 单例（首次调用时自动初始化）"""
    global _memory_store
    if _memory_store is None:
        from ..config.settings import Settings
        _memory_store = MemoryStore(Settings.get().data_dir / "memory_db")
    return _memory_store


class MemoryStore:
    """基于 ChromaDB 的记忆存储，支持语义检索和维度过滤。

    用法:
        store = MemoryStore(data_dir / "memory_db")
        store.add("hobbies", "离职后开发了微信小程序...", {"keywords": ["编程", "小程序"]})
        results = store.search("你最近在做什么项目", top_k=5)
    """

    def __init__(self, persist_dir: Path, half_life_days: float = 30.0):
        self._dir = Path(persist_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self._dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._embedder = MemoryEmbedder.get()
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._half_life_days = half_life_days
        log.info("MemoryStore 初始化完成, dir=%s, count=%d, half_life=%.0fd",
                 self._dir, self._collection.count(), self._half_life_days)

    # ── CRUD ──────────────────────────────────────────────

    def add(self, dimension: str, content: str, metadata: dict | None = None) -> str:
        """添加一条记忆，自动写入 strength / last_accessed_at / access_count。"""
        mem_id = f"mem_{uuid.uuid4().hex[:12]}"
        embedding = self._embedder.encode_single(content)
        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "dimension": dimension,
            "strength": 1.0,
            "last_accessed_at": now,
            "access_count": 0,
            **(metadata or {}),
        }
        self._collection.add(
            ids=[mem_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[meta],
        )
        log.debug("记忆已添加, id=%s, dim=%s, len=%d", mem_id, dimension, len(content))
        return mem_id

    def search(self, query: str, top_k: int = 5,
               dimensions: list[str] | None = None) -> list[dict]:
        """语义检索 + 时间衰减重排序。

        先按语义相似度拉取 fetch_k（top_k × 3）条候选，
        再按 combined = similarity × effective_strength 降序重排，
        取前 top_k 条，并强化命中记忆的 strength。
        """
        if self._collection.count() == 0:
            return []

        fetch_k = min(top_k * 3, self._collection.count())
        query_emb = self._embedder.encode_single(query)
        where = None
        if dimensions:
            where = {"dimension": {"$in": dimensions}}

        results = self._collection.query(
            query_embeddings=[query_emb],
            n_results=fetch_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        scored: list[dict] = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i] or {}
                distance = results["distances"][0][i]
                similarity = 1.0 - distance  # cosine 距离 → 相似度
                eff_strength = self._compute_effective_strength(meta)
                combined = similarity * eff_strength
                scored.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": meta,
                    "distance": distance,
                    "strength": eff_strength,
                    "combined": combined,
                })

        # 按 combined 降序，取 top_k
        scored.sort(key=lambda e: e["combined"], reverse=True)
        entries = scored[:top_k]

        # 强化被检索命中的记忆（strength boost）
        if entries:
            self._boost(entries)

        return entries

    # ── 遗忘与衰减 ──────────────────────────────────────

    def _compute_effective_strength(self, meta: dict) -> float:
        """计算有效强度：base_strength × 时间衰减因子。

        衰减公式: 0.5 ^ (days_since_last_access / half_life_days)
        无时间戳的旧数据视为刚刚创建（向后兼容）。
        """
        strength = float(meta.get("strength", 1.0))
        last_accessed = meta.get("last_accessed_at")
        if last_accessed is None:
            return strength

        try:
            last_dt = datetime.fromisoformat(str(last_accessed))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days = (now - last_dt).total_seconds() / 86400.0
            if days < 0:
                days = 0.0
            decay = 0.5 ** (days / self._half_life_days)
            return strength * decay
        except (ValueError, TypeError, OverflowError):
            return strength

    def _boost(self, entries: list[dict]) -> None:
        """强化被检索命中的记忆：strength += 0.15（上限 1.0），更新 last_accessed_at。"""
        now = datetime.now(timezone.utc).isoformat()
        ids = [e["id"] for e in entries]

        # 获取当前元数据（ChromaDB update 是全量替换，需要保留其他字段）
        result = self._collection.get(ids=ids, include=["metadatas"])
        id_to_meta = {}
        if result["ids"]:
            for i, mem_id in enumerate(result["ids"]):
                id_to_meta[mem_id] = result["metadatas"][i] if result["metadatas"] else {}

        for entry in entries:
            meta = id_to_meta.get(entry["id"], entry["metadata"])
            eff_strength = entry.get("strength", self._compute_effective_strength(meta))
            new_strength = min(1.0, eff_strength + 0.15)
            access_count = int(meta.get("access_count", 0)) + 1
            self._collection.update(
                ids=[entry["id"]],
                metadatas=[{
                    **meta,
                    "strength": new_strength,
                    "last_accessed_at": now,
                    "access_count": access_count,
                }],
            )

        log.debug("记忆强化完成, boosted=%d", len(entries))

    def get_by_dimension(self, dimension: str) -> list[dict]:
        """获取某个维度的全部记忆。"""
        result = self._collection.get(
            where={"dimension": dimension},
            include=["documents", "metadatas"],
        )
        entries: list[dict] = []
        if result["ids"]:
            for i in range(len(result["ids"])):
                entries.append({
                    "id": result["ids"][i],
                    "document": result["documents"][i],
                    "metadata": result["metadatas"][i],
                })
        return entries

    def delete_by_dimension(self, dimension: str) -> int:
        """删除某维度的全部记忆。返回删除数。"""
        existing = self.get_by_dimension(dimension)
        if existing:
            ids = [e["id"] for e in existing]
            self._collection.delete(ids=ids)
            log.info("记忆维度已清空, dim=%s, deleted=%d", dimension, len(ids))
        return len(existing)

    def upsert_dimension(self, dimension: str, entries: list[dict]) -> int:
        """全量刷新某个维度的记忆（先删后加）。返回新增条数。"""
        self.delete_by_dimension(dimension)
        count = 0
        for entry in entries:
            content = entry.get("content", "")
            if not content:
                continue
            meta = {k: v for k, v in entry.items() if k != "content"}
            meta["dimension"] = dimension
            self.add(dimension, content, meta)
            count += 1
        log.info("记忆维度已刷新, dim=%s, count=%d", dimension, count)
        return count

    @property
    def count(self) -> int:
        return self._collection.count()

    def stats(self) -> dict:
        """各维度记忆数量统计。"""
        result = self._collection.get(include=["metadatas"])
        dims: dict[str, int] = {}
        if result["metadatas"]:
            for meta in result["metadatas"]:
                d = meta.get("dimension", "unknown")
                dims[d] = dims.get(d, 0) + 1
        return {"total": self._collection.count(), "by_dimension": dims}
