import json
import sqlite3

import pytest

from src.agent.conversation_store import ConversationStore


def test_replace_and_load_round_trip_in_order(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    messages = [
        {"role": "system", "content": "摘要"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]

    store.replace(messages)

    assert store.load() == messages
    assert store.path.is_file()


def test_replace_is_transactional_when_a_message_is_invalid(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    original = [{"role": "user", "content": "保留我"}]
    store.replace(original)

    with pytest.raises(ValueError, match="role"):
        store.replace([
            {"role": "user", "content": "新内容"},
            {"role": "tool", "content": "不支持"},
        ])

    assert store.load() == original


def test_legacy_json_is_imported_once_and_preserved(tmp_path):
    legacy = tmp_path / "conversation.json"
    legacy.write_text(
        json.dumps([{"role": "user", "content": "旧会话"}], ensure_ascii=False),
        encoding="utf-8",
    )
    store = ConversationStore(tmp_path / "conversation.sqlite3")

    assert store.migrate_json_once(legacy) is True
    assert store.load() == [{"role": "user", "content": "旧会话"}]
    assert legacy.exists()

    store.clear()
    assert store.migrate_json_once(legacy) is False
    assert store.load() == []


def test_invalid_legacy_json_can_be_fixed_and_retried(tmp_path):
    legacy = tmp_path / "conversation.json"
    legacy.write_text("not json", encoding="utf-8")
    store = ConversationStore(tmp_path / "conversation.sqlite3")

    with pytest.raises(ValueError, match="conversation JSON"):
        store.migrate_json_once(legacy)

    legacy.write_text('[{"role":"assistant","content":"已修复"}]', encoding="utf-8")
    assert store.migrate_json_once(legacy) is True
    assert store.load()[0]["content"] == "已修复"


def test_database_enforces_supported_roles(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")

    with pytest.raises(sqlite3.IntegrityError):
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "INSERT INTO conversation_messages(position, role, content) VALUES(0, ?, ?)",
                ("tool", "unsupported"),
            )
