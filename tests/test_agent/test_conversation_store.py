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


def test_conversation_revision_and_completed_run_are_committed_together(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")

    assert store.revision() == 0
    assert store.last_completed_run_id() is None

    store.replace(
        [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ],
        completed_run_id="chat_1",
    )

    assert store.revision() == 1
    assert store.last_completed_run_id() == "chat_1"

    # Bounded history may keep the same number of messages, so recovery must
    # not infer progress from message count alone.
    store.replace(
        [
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "第二轮回复"},
        ],
        completed_run_id="chat_2",
    )
    assert store.revision() == 2
    assert store.last_completed_run_id() == "chat_2"


def test_chat_run_checkpoint_round_trip_and_clear(tmp_path):
    store = ConversationStore(tmp_path / "conversation.sqlite3")
    checkpoint = {
        "id": "chat_1",
        "response_id": "reply_1",
        "user_message": "你好",
        "status": "running",
        "response_text": "正在",
        "instruct_text": "自然地说",
        "retrieved_memories": [{"id": "memory_1", "metadata": {"dimension": "event"}}],
        "safety_state": "normal",
        "first_response_ms": 12,
        "total_response_ms": 0,
        "revision": 3,
        "base_history_revision": 0,
        "error": None,
    }

    store.save_run_checkpoint(checkpoint)
    assert store.load_run_checkpoints() == [checkpoint]

    checkpoint["status"] = "completed"
    checkpoint["response_text"] = "正在回复"
    checkpoint["revision"] = 4
    store.save_run_checkpoint(checkpoint)
    assert store.load_run_checkpoints() == [checkpoint]

    store.clear()
    assert store.load_run_checkpoints() == []
    assert store.last_completed_run_id() is None


def test_existing_v1_database_upgrades_without_losing_conversation(tmp_path):
    path = tmp_path / "conversation.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE conversation_messages (
                position INTEGER PRIMARY KEY,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE TABLE conversation_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO conversation_messages(position, role, content)
                VALUES(0, 'user', '旧版本会话');
            PRAGMA user_version = 1;
            """
        )

    store = ConversationStore(path)

    assert store.load() == [{"role": "user", "content": "旧版本会话"}]
    assert store.load_run_checkpoints() == []
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
