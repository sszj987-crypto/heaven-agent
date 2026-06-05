"""ChromaDB 记忆存储：持久化向量索引 + 元数据过滤"""

import uuid
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

    def __init__(self, persist_dir: Path):
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
        log.info("MemoryStore 初始化完成, dir=%s, count=%d",
                 self._dir, self._collection.count())

    # ── CRUD ──────────────────────────────────────────────

    def add(self, dimension: str, content: str, metadata: dict | None = None) -> str:
        """添加一条记忆。返回生成的 id。"""
        mem_id = f"mem_{uuid.uuid4().hex[:12]}"
        embedding = self._embedder.encode_single(content)
        meta = {
            "dimension": dimension,
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
        """语义检索相关记忆。可过滤指定维度。"""
        if self._collection.count() == 0:
            return []

        query_emb = self._embedder.encode_single(query)
        where = None
        if dimensions:
            where = {"dimension": {"$in": dimensions}}

        results = self._collection.query(
            query_embeddings=[query_emb],
            n_results=min(top_k, self._collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        entries: list[dict] = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                entries.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })
        return entries

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
