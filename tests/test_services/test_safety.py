from src.services.safety import SafetyPolicy


def test_direct_self_harm_language_enters_crisis_mode():
    policy = SafetyPolicy()

    decision = policy.evaluate("我不想活了，想结束自己的生命")

    assert decision.state == "crisis"
    assert "现实中" in decision.response
    assert "紧急" in decision.response


def test_overwhelmed_language_uses_supportive_redirect():
    policy = SafetyPolicy()

    decision = policy.evaluate("我最近真的很绝望，快撑不住了")

    assert decision.state == "supportive_redirect"
    assert decision.response is None


def test_normal_grief_language_does_not_trigger_crisis_mode():
    policy = SafetyPolicy()

    decision = policy.evaluate("奶奶，我今天又想你了")

    assert decision.state == "normal"
    assert decision.response is None
