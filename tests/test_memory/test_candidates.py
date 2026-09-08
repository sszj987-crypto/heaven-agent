import pytest

from src.memory.candidates import CandidateNotFound, CandidateStateError, CandidateStore


def test_candidate_lifecycle_preserves_source_and_allows_edit(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    created = store.add(
        dimension="life_experiences",
        content="我每年中秋做桂花糕",
        source_type="conversation",
        source_excerpt="奶奶每年中秋都会做桂花糕",
        confidence=0.91,
    )

    assert store.list("pending")[0].source_excerpt == "奶奶每年中秋都会做桂花糕"

    approved = store.resolve(created.id, "approved", "我以前每年中秋都会做桂花糕")

    assert approved.status == "approved"
    assert approved.content == "我以前每年中秋都会做桂花糕"
    assert store.list("pending") == []


def test_rejected_candidate_remains_auditable(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    created = store.add(
        dimension="personal_traits",
        content="喜欢钓鱼",
        source_type="import",
        source_excerpt="聊天原文",
        confidence=0.7,
    )

    store.resolve(created.id, "rejected")

    assert store.list("rejected")[0].id == created.id


def test_unknown_candidate_cannot_be_resolved(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")

    with pytest.raises(CandidateNotFound):
        store.resolve("missing", "approved")


def test_resolved_candidate_cannot_be_resolved_twice(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    created = store.add(
        dimension="personal_traits",
        content="喜欢钓鱼",
        source_type="conversation",
        source_excerpt="原话",
        confidence=0.8,
    )
    store.resolve(created.id, "approved")

    with pytest.raises(CandidateStateError):
        store.resolve(created.id, "rejected")


def test_extract_by_source_type_removes_only_matching_candidates(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    conversation = store.add(
        dimension="relationships",
        content="用户对话中的事实",
        source_type="conversation",
        source_excerpt="私密对话原文",
        confidence=0.7,
    )
    imported = store.add(
        dimension="relationships",
        content="导入资料中的事实",
        source_type="import_dimension",
        source_excerpt="导入资料",
        confidence=0.9,
    )

    extracted = store.extract_by_source_type("conversation")

    assert [item.id for item in extracted] == [conversation.id]
    assert [item.id for item in store.list(None)] == [imported.id]
