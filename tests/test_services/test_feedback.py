from src.services.feedback import FeedbackStore


def test_feedback_store_upserts_atomically_and_aggregates_reasons(tmp_path):
    path = tmp_path / "feedback.json"
    store = FeedbackStore(path)

    first = store.upsert(
        response_id="reply_1",
        user_message="你好吗",
        response_text="我很好",
        rating="dissimilar",
        reasons=["style", "style", "fact"],
        suggestion="她会更简短。",
    )
    replacement = store.upsert(
        response_id="reply_1",
        user_message="你好吗",
        response_text="我很好",
        rating="similar",
    )

    assert path.exists()
    assert first.reasons == ("style", "fact")
    assert replacement.created_at == first.created_at
    assert replacement.updated_at >= first.updated_at
    assert store.stats() == {
        "total": 1,
        "similar": 1,
        "dissimilar": 0,
        "similar_rate": 1.0,
        "reasons": {"fact": 0, "other": 0, "relationship": 0, "response": 0, "style": 0},
    }


def test_similar_feedback_rejects_dissimilar_reasons(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")

    import pytest
    with pytest.raises(ValueError, match="cannot include reasons"):
        store.upsert(
            response_id="reply_1",
            user_message="你好吗",
            response_text="我很好",
            rating="similar",
            reasons=["style"],
        )
