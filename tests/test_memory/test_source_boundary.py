from src.memory.store import MemoryStore


class SearchCollection:
    def __init__(self):
        self.where = None

    def count(self):
        return 1

    def query(self, **kwargs):
        self.where = kwargs["where"]
        return {
            "ids": [["profile_1"]],
            "documents": [["喜欢桂花糕"]],
            "metadatas": [[{
                "dimension": "personal_traits",
                "source_type": "profile",
                "strength": 1.0,
                "last_accessed_at": "2099-01-01T00:00:00+00:00",
                "access_count": 0,
            }]],
            "distances": [[0.1]],
        }

    def get(self, ids=None, include=None):
        return {"ids": ids or [], "metadatas": []}

    def update(self, **_kwargs):
        return None


class MigrationCollection:
    def __init__(self):
        self.deleted = []
        self.updated = None

    def get(self, include=None):
        return {
            "ids": ["legacy_fact", "generated_summary"],
            "metadatas": [
                {"dimension": "personal_traits"},
                {"dimension": "conversation", "type": "chat_summary"},
            ],
        }

    def delete(self, ids):
        self.deleted.extend(ids)

    def update(self, ids, metadatas):
        self.updated = (ids, metadatas)


class FakeEmbedder:
    def encode_single(self, _text):
        return [0.1]


def _store_with(collection):
    store = MemoryStore.__new__(MemoryStore)
    store._collection = collection
    store._embedder = FakeEmbedder()
    store._half_life_days = 30.0
    return store


def test_profile_retrieval_explicitly_filters_source_type():
    collection = SearchCollection()
    store = _store_with(collection)

    results = store.search("喜欢什么", source_types=["profile"])

    assert results[0]["metadata"]["source_type"] == "profile"
    assert collection.where == {"source_type": {"$in": ["profile"]}}


def test_source_migration_removes_generated_summaries_and_marks_legacy_facts():
    collection = MigrationCollection()
    store = _store_with(collection)

    result = store.migrate_source_types()

    assert result == {"removed_summaries": 1, "marked_profile": 1}
    assert collection.deleted == ["generated_summary"]
    assert collection.updated == (["legacy_fact"], [{
        "dimension": "personal_traits",
        "source_type": "profile",
    }])
