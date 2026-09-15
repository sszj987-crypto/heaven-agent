from src.agent.context_budget import ContextBudgeter


def test_budget_preserves_system_edges_current_user_and_dialect():
    system = "CORE:" + "人物资料" * 100 + ":OUTPUT-CONTRACT"
    history = [
        {"role": "user", "content": "旧问题" * 40},
        {"role": "assistant", "content": "旧回答" * 40},
    ]

    result = ContextBudgeter(max_chars=240).build(
        system_prompt=system,
        history=history,
        current_user="当前问题",
        dialect_instruction="粤语约束",
    )

    assert sum(len(message["content"]) for message in result.messages) <= 240
    assert result.messages[0]["content"].startswith("CORE:")
    assert result.messages[0]["content"].endswith(":OUTPUT-CONTRACT")
    assert "中间资料因上下文预算已省略" in result.messages[0]["content"]
    assert result.messages[-2] == {"role": "system", "content": "粤语约束"}
    assert result.messages[-1] == {"role": "user", "content": "当前问题"}


def test_budget_does_not_compact_system_when_whole_request_fits():
    system = "CORE:" + "人物资料" * 30 + ":OUTPUT-CONTRACT"

    result = ContextBudgeter(max_chars=500).build(
        system_prompt=system,
        history=[],
        current_user="current",
    )

    assert result.messages[0]["content"] == system
    assert result.stats.system_compacted is False


def test_budget_keeps_newest_complete_turns_without_orphan_messages():
    history = [
        {"role": "user", "content": "u1" * 20},
        {"role": "assistant", "content": "a1" * 20},
        {"role": "user", "content": "u2" * 20},
        {"role": "assistant", "content": "a2" * 20},
        {"role": "user", "content": "u3" * 20},
        {"role": "assistant", "content": "a3" * 20},
    ]

    result = ContextBudgeter(max_chars=105).build(
        system_prompt="system",
        history=history,
        current_user="current",
    )

    contents = [message["content"] for message in result.messages]
    assert "u3" * 20 in contents
    assert "a3" * 20 in contents
    assert "u2" * 20 not in contents
    assert "a2" * 20 not in contents
    assert result.stats.dropped_history_messages == 4


def test_recent_dialogue_has_priority_over_old_summary():
    history = [
        {"role": "system", "content": "旧摘要" * 40},
        {"role": "user", "content": "最近问题"},
        {"role": "assistant", "content": "最近回答"},
    ]

    result = ContextBudgeter(max_chars=40).build(
        system_prompt="system",
        history=history,
        current_user="current",
    )

    contents = [message["content"] for message in result.messages]
    assert "最近问题" in contents
    assert "最近回答" in contents
    assert not any("旧摘要" in content for content in contents)


def test_budget_does_not_mutate_persisted_history():
    history = [
        {"role": "user", "content": "很长的问题" * 20},
        {"role": "assistant", "content": "很长的回答" * 20},
    ]
    original = [dict(message) for message in history]

    ContextBudgeter(max_chars=30).build(
        system_prompt="system",
        history=history,
        current_user="current",
    )

    assert history == original


def test_budget_drops_incomplete_history_turns():
    history = [
        {"role": "assistant", "content": "orphan assistant"},
        {"role": "user", "content": "complete user"},
        {"role": "assistant", "content": "complete assistant"},
        {"role": "user", "content": "orphan user"},
    ]

    result = ContextBudgeter(max_chars=200).build(
        system_prompt="system",
        history=history,
        current_user="current",
    )

    contents = [message["content"] for message in result.messages]
    assert "complete user" in contents
    assert "complete assistant" in contents
    assert "orphan assistant" not in contents
    assert "orphan user" not in contents
    assert result.stats.dropped_history_messages == 2


def test_mandatory_content_can_report_overflow_without_dropping_current_input():
    result = ContextBudgeter(max_chars=5).build(
        system_prompt="system",
        history=[],
        current_user="current-user",
    )

    assert result.messages[-1]["content"] == "current-user"
    assert result.stats.overflow_chars > 0
