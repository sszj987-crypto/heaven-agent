from types import SimpleNamespace

from src.memory.candidates import CandidateStore
from src.services.imports import ImportReviewService
from src.soul.skill_card import SkillCard


def test_import_result_is_queued_as_reviewable_candidates(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    service = ImportReviewService(store)
    result = SimpleNamespace(
        changes=["personality"],
        profile={"personality": "- 乐观开朗"},
        skill_card=SkillCard(expression_dna="多用短句"),
    )

    queued = service.queue(result, "用户: 你总是很乐观\n本人: 哈哈")

    assert [item.source_type for item in queued] == [
        "import_dimension",
        "import_skill",
    ]
    assert queued[0].dimension == "personality"
    assert queued[0].content == "- 乐观开朗"
    assert "expression_dna" in queued[1].content
    assert all(item.status == "pending" for item in queued)


def test_import_excerpt_is_bounded_and_empty_skill_is_ignored(tmp_path):
    store = CandidateStore(tmp_path / "candidates.json")
    service = ImportReviewService(store, excerpt_limit=20)
    result = SimpleNamespace(
        changes=["basic_info"],
        profile={"basic_info": "姓名：小安"},
        skill_card=SkillCard(),
    )

    queued = service.queue(result, "a" * 100)

    assert len(queued) == 1
    assert len(queued[0].source_excerpt) == 20
