import pytest

from src.services.narrative import NarrativePolicy


@pytest.mark.parametrize(
    "message",
    [
        "你去世以后还好吗",
        "奶奶，你在那边好吗",
        "天堂里的你过得怎么样",
        "自从你走了以后，我一直很想你",
    ],
)
def test_explicit_persona_afterlife_topics_are_allowed(message):
    assert NarrativePolicy().evaluate(message).afterlife_topic_allowed is True


@pytest.mark.parametrize(
    "message",
    [
        "你好",
        "你最近还好吗",
        "今天吃饭了吗",
        "我的朋友去世了，我很难过",
    ],
)
def test_ordinary_or_third_party_topics_do_not_enable_persona_afterlife(message):
    assert NarrativePolicy().evaluate(message).afterlife_topic_allowed is False


def test_unprompted_persona_afterlife_claim_is_detected():
    policy = NarrativePolicy()

    assert policy.output_violation(
        "我没事，在这边挺好的！",
        afterlife_topic_allowed=False,
    ) == "self_afterlife_location"
    assert policy.output_violation(
        "我没事，在这边挺好的！",
        afterlife_topic_allowed=True,
    ) is None


def test_profile_redaction_keeps_a_relatives_death_but_removes_persona_status():
    text = "- 2020年老伴因病去世\n- 我已去世，目前在天堂。\n离世年份: 2026"

    visible = NarrativePolicy().redact_profile_text(
        text,
        afterlife_topic_allowed=False,
    )

    assert "老伴因病去世" in visible
    assert "我已去世" not in visible
    assert "离世年份" not in visible
