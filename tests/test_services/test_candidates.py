import json

import pytest

from src.memory.candidates import CandidateStateError, CandidateStore
from src.services.candidates import CandidateService
from src.soul.skill_card import SkillCard


class FakeLoader:
    def __init__(self):
        self.values = {"personal_traits": "# 个人特质\n"}
        self.skill = None

    def load_dimension(self, dimension):
        return self.values.get(dimension, "")

    def save_dimension(self, dimension, content):
        self.values[dimension] = content

    def save_skill(self, skill):
        self.skill = skill


class FailingLoader(FakeLoader):
    def save_dimension(self, dimension, content):
        raise OSError("disk full")


class FailingResolveStore(CandidateStore):
    def __init__(self, path):
        super().__init__(path)
        self.fail_next_resolve = True

    def resolve(self, candidate_id, status, edited_content=None):
        if self.fail_next_resolve:
            self.fail_next_resolve = False
            raise OSError("candidate store unavailable")
        return super().resolve(candidate_id, status, edited_content)


def test_approve_appends_reviewed_fact_and_invalidates_prompt(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    candidate = store.add(
        dimension="personal_traits",
        content="喜欢钓鱼",
        source_type="conversation",
        source_excerpt="原话",
        confidence=0.8,
    )
    loader = FakeLoader()
    invalidations = []
    service = CandidateService(store, loader, lambda: invalidations.append(True))

    resolved = service.approve(candidate.id, "我喜欢在河边钓鱼")

    assert resolved.status == "approved"
    assert "我喜欢在河边钓鱼" in loader.values["personal_traits"]
    assert invalidations == [True]


def test_reject_does_not_change_profile(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    candidate = store.add(
        dimension="personal_traits",
        content="喜欢钓鱼",
        source_type="conversation",
        source_excerpt="原话",
        confidence=0.8,
    )
    loader = FakeLoader()
    service = CandidateService(store, loader, lambda: None)

    service.reject(candidate.id)

    assert loader.values["personal_traits"] == "# 个人特质\n"


def test_approve_import_replaces_complete_dimension(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    candidate = store.add(
        dimension="personality",
        content="- 乐观开朗\n- 幽默风趣",
        source_type="import_dimension",
        source_excerpt="原始导入片段",
        confidence=0.9,
    )
    loader = FakeLoader()
    loader.values["personality"] = "- 安静内敛"
    service = CandidateService(store, loader, lambda: None)

    service.approve(candidate.id)

    assert loader.values["personality"] == "- 乐观开朗\n- 幽默风趣"


def test_approve_import_skill_saves_skill_card(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    content = json.dumps({"expression_dna": "多用短句"}, ensure_ascii=False)
    candidate = store.add(
        dimension="skill",
        content=content,
        source_type="import_skill",
        source_excerpt="原始导入片段",
        confidence=0.85,
    )
    loader = FakeLoader()
    service = CandidateService(store, loader, lambda: None)

    service.approve(candidate.id)

    assert isinstance(loader.skill, SkillCard)
    assert loader.skill.expression_dna == "多用短句"


def test_approve_keeps_candidate_pending_when_profile_save_fails(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    candidate = store.add(
        dimension="personal_traits",
        content="喜欢钓鱼",
        source_type="conversation",
        source_excerpt="原话",
        confidence=0.8,
    )
    service = CandidateService(store, FailingLoader(), lambda: None)

    with pytest.raises(OSError, match="disk full"):
        service.approve(candidate.id)

    stored = next(item for item in store.list(None) if item.id == candidate.id)
    assert stored.status == "pending"


def test_repeated_approval_does_not_append_the_fact_again(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    candidate = store.add(
        dimension="personal_traits",
        content="喜欢钓鱼",
        source_type="conversation",
        source_excerpt="原话",
        confidence=0.8,
    )
    loader = FakeLoader()
    service = CandidateService(store, loader, lambda: None)
    service.approve(candidate.id)
    saved = loader.values["personal_traits"]

    with pytest.raises(CandidateStateError):
        service.approve(candidate.id)

    assert loader.values["personal_traits"] == saved


def test_retry_after_candidate_state_write_failure_is_idempotent(tmp_path):
    store = FailingResolveStore(tmp_path / "candidates.json")
    candidate = store.add(
        dimension="personal_traits",
        content="喜欢钓鱼",
        source_type="conversation",
        source_excerpt="原话",
        confidence=0.8,
    )
    loader = FakeLoader()
    service = CandidateService(store, loader, lambda: None)

    with pytest.raises(OSError, match="candidate store unavailable"):
        service.approve(candidate.id)
    service.approve(candidate.id)

    assert loader.values["personal_traits"].count("- 喜欢钓鱼") == 1
