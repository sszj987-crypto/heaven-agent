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
_CONVERSATION_REVISION_KEY = "conversation_revision"
_LAST_COMPLETED_RUN_KEY = "last_completed_chat_run_id"
_SUPPORTED_RUN_STATUSES = frozenset(
    {"pending", "running", "completed", "failed", "cancelled"}
)


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

    def replace(
        self,
        messages: list[dict],
        *,
        completed_run_id: str | None = None,
    ) -> None:
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
            self._increment_revision(connection)
            self._set_last_completed_run(connection, completed_run_id)
            self._mark_legacy_migrated(connection)
        log.info("SQLite 会话保存完成, messages=%d", len(normalized))

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM conversation_messages")
            connection.execute("DELETE FROM conversation_runs")
            connection.execute(
                "DELETE FROM conversation_metadata WHERE key = ?",
                (_LAST_COMPLETED_RUN_KEY,),
            )
            self._increment_revision(connection)
            self._mark_legacy_migrated(connection)
        log.info("SQLite 会话已清空")

    def revision(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM conversation_metadata WHERE key = ?",
                (_CONVERSATION_REVISION_KEY,),
            ).fetchone()
        if row is None:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError):
            log.warning("SQLite 会话修订号无效，按 0 处理")
            return 0

    def last_completed_run_id(self) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM conversation_metadata WHERE key = ?",
                (_LAST_COMPLETED_RUN_KEY,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def save_run_checkpoint(self, checkpoint: dict) -> None:
        normalized = self._validate_run_checkpoint(checkpoint)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_runs(
                    run_id, response_id, user_message, status, response_text,
                    instruct_text, retrieved_memories, safety_state,
                    first_response_ms, total_response_ms, revision,
                    base_history_revision, error, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    response_id = excluded.response_id,
                    user_message = excluded.user_message,
                    status = excluded.status,
                    response_text = excluded.response_text,
                    instruct_text = excluded.instruct_text,
                    retrieved_memories = excluded.retrieved_memories,
                    safety_state = excluded.safety_state,
                    first_response_ms = excluded.first_response_ms,
                    total_response_ms = excluded.total_response_ms,
                    revision = excluded.revision,
                    base_history_revision = excluded.base_history_revision,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized["id"],
                    normalized["response_id"],
                    normalized["user_message"],
                    normalized["status"],
                    normalized["response_text"],
                    normalized["instruct_text"],
                    json.dumps(normalized["retrieved_memories"], ensure_ascii=False),
                    normalized["safety_state"],
                    normalized["first_response_ms"],
                    normalized["total_response_ms"],
                    normalized["revision"],
                    normalized["base_history_revision"],
                    normalized["error"],
                    now,
                    now,
                ),
            )

    def load_run_checkpoints(self, *, limit: int | None = None) -> list[dict]:
        query = """
            SELECT run_id, response_id, user_message, status, response_text,
                   instruct_text, retrieved_memories, safety_state,
                   first_response_ms, total_response_ms, revision,
                   base_history_revision, error
            FROM conversation_runs
            ORDER BY sequence
        """
        with self._lock, self._connect() as connection:
            rows = connection.execute(query).fetchall()
        if limit is not None:
            if limit < 1:
                return []
            rows = rows[-limit:]

        checkpoints = []
        for row in rows:
            memories = json.loads(row[6])
            checkpoint = {
                "id": row[0],
                "response_id": row[1],
                "user_message": row[2],
                "status": row[3],
                "response_text": row[4],
                "instruct_text": row[5],
                "retrieved_memories": memories,
                "safety_state": row[7],
                "first_response_ms": row[8],
                "total_response_ms": row[9],
                "revision": row[10],
                "base_history_revision": row[11],
                "error": row[12],
            }
            checkpoints.append(self._validate_run_checkpoint(checkpoint))
        return checkpoints

    def delete_run_checkpoints(self, run_ids: list[str]) -> None:
        if not run_ids:
            return
        placeholders = ", ".join("?" for _ in run_ids)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"DELETE FROM conversation_runs WHERE run_id IN ({placeholders})",
                tuple(run_ids),
            )

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
                    self._increment_revision(connection)
                    self._set_last_completed_run(connection, None)
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
                CREATE TABLE IF NOT EXISTS conversation_runs (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    response_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'pending', 'running', 'completed', 'failed', 'cancelled'
                    )),
                    response_text TEXT NOT NULL,
                    instruct_text TEXT NOT NULL,
                    retrieved_memories TEXT NOT NULL,
                    safety_state TEXT NOT NULL,
                    first_response_ms INTEGER,
                    total_response_ms INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    base_history_revision INTEGER NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversation_runs_status_idx
                    ON conversation_runs(status);
                PRAGMA user_version = 2;
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
    def _increment_revision(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO conversation_metadata(key, value) VALUES(?, '1')
            ON CONFLICT(key) DO UPDATE SET
                value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            """,
            (_CONVERSATION_REVISION_KEY,),
        )

    @staticmethod
    def _set_last_completed_run(
        connection: sqlite3.Connection,
        run_id: str | None,
    ) -> None:
        if run_id is None:
            connection.execute(
                "DELETE FROM conversation_metadata WHERE key = ?",
                (_LAST_COMPLETED_RUN_KEY,),
            )
            return
        connection.execute(
            "INSERT OR REPLACE INTO conversation_metadata(key, value) VALUES(?, ?)",
            (_LAST_COMPLETED_RUN_KEY, run_id),
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

    @staticmethod
    def _validate_run_checkpoint(checkpoint) -> dict:
        if not isinstance(checkpoint, dict):
            raise ValueError("chat run checkpoint must be an object")
        required_text = (
            "id",
            "response_id",
            "user_message",
            "response_text",
            "instruct_text",
            "safety_state",
        )
        for key in required_text:
            if not isinstance(checkpoint.get(key), str):
                raise ValueError(f"chat run checkpoint {key} must be text")
        status = checkpoint.get("status")
        if status not in _SUPPORTED_RUN_STATUSES:
            raise ValueError("unsupported chat run status")
        memories = checkpoint.get("retrieved_memories")
        if not isinstance(memories, list) or not all(
            isinstance(item, dict) for item in memories
        ):
            raise ValueError("chat run memories must be a list of objects")
        first_response_ms = checkpoint.get("first_response_ms")
        if first_response_ms is not None and not isinstance(first_response_ms, int):
            raise ValueError("chat run first response timing must be an integer")
        error = checkpoint.get("error")
        if error is not None and not isinstance(error, str):
            raise ValueError("chat run error must be text")
        normalized = dict(checkpoint)
        for key in ("total_response_ms", "revision", "base_history_revision"):
            value = checkpoint.get(key)
            if not isinstance(value, int):
                raise ValueError(f"chat run checkpoint {key} must be an integer")
        normalized["retrieved_memories"] = [dict(item) for item in memories]
        return normalized
