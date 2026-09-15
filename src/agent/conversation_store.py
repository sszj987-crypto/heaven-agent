"""Transactional SQLite storage for one Soul's active conversation."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config.logger import get_logger

log = get_logger("conversation_store")

_SUPPORTED_ROLES = frozenset({"system", "user", "assistant"})
_LEGACY_MIGRATION_KEY = "legacy_json_migrated"


class ConversationStore:
    """Persist the bounded active conversation as one atomic SQLite snapshot."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def load(self) -> list[dict]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM conversation_messages ORDER BY position"
            ).fetchall()
        messages = [{"role": role, "content": content} for role, content in rows]
        log.info("SQLite 会话加载完成, messages=%d", len(messages))
        return messages

    def replace(self, messages: list[dict]) -> None:
        normalized = self._validate(messages)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM conversation_messages")
            connection.executemany(
                "INSERT INTO conversation_messages(position, role, content) "
                "VALUES(?, ?, ?)",
                [
                    (position, message["role"], message["content"])
                    for position, message in enumerate(normalized)
                ],
            )
            self._mark_legacy_migrated(connection)
        log.info("SQLite 会话保存完成, messages=%d", len(normalized))

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM conversation_messages")
            self._mark_legacy_migrated(connection)
        log.info("SQLite 会话已清空")

    def migrate_json_once(self, legacy_path: str | Path) -> bool:
        """Import legacy JSON once without deleting it or replacing SQLite data."""
        legacy_path = Path(legacy_path)
        with self._lock:
            if self._migration_completed():
                return False

            messages: list[dict] = []
            if legacy_path.exists():
                try:
                    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
                    messages = self._validate(payload)
                except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
                    raise ValueError("invalid legacy conversation JSON") from exc

            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                already_has_messages = connection.execute(
                    "SELECT 1 FROM conversation_messages LIMIT 1"
                ).fetchone()
                imported = bool(messages) and not already_has_messages
                if imported:
                    connection.executemany(
                        "INSERT INTO conversation_messages(position, role, content) "
                        "VALUES(?, ?, ?)",
                        [
                            (position, message["role"], message["content"])
                            for position, message in enumerate(messages)
                        ],
                    )
                self._mark_legacy_migrated(connection)

        log.info(
            "旧会话 JSON 迁移检查完成, imported=%s, legacy_preserved=%s",
            imported,
            legacy_path.exists(),
        )
        return imported

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    position INTEGER PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
                    content TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                PRAGMA user_version = 1;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _migration_completed(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversation_metadata WHERE key = ?",
                (_LEGACY_MIGRATION_KEY,),
            ).fetchone()
        return row is not None

    @staticmethod
    def _mark_legacy_migrated(connection: sqlite3.Connection) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO conversation_metadata(key, value) VALUES(?, ?)",
            (_LEGACY_MIGRATION_KEY, datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def _validate(messages) -> list[dict]:
        if not isinstance(messages, list):
            raise ValueError("conversation must be a list")
        normalized: list[dict] = []
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("conversation message must be an object")
            role = message.get("role")
            content = message.get("content")
            if role not in _SUPPORTED_ROLES:
                raise ValueError("unsupported conversation role")
            if not isinstance(content, str):
                raise ValueError("conversation content must be text")
            normalized.append({"role": role, "content": content})
        return normalized
