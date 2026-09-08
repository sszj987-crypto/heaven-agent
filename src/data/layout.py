from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .files import atomic_write_text


@dataclass(frozen=True)
class MigrationResult:
    backup_dir: Path
    copied: tuple[Path, ...]


class SoulDataLayout:
    """All mutable data belonging to one Soul."""

    def __init__(self, data_root: Path, soul_id: str = "default"):
        if not soul_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in soul_id):
            raise ValueError("soul_id may contain only letters, numbers, '-' and '_'")
        self.data_root = Path(data_root)
        self.soul_id = soul_id
        self.soul_dir = self.data_root / "souls" / soul_id
        self.profile_dir = self.soul_dir / "profile"
        self.voice_dir = self.soul_dir / "voice"
        self.daily_dir = self.soul_dir / "memory" / "daily"
        self.memory_db_dir = self.soul_dir / "memory" / "index"
        self.conversation_path = self.soul_dir / "conversation.json"
        self.candidates_path = self.soul_dir / "memory" / "candidates.json"
        self.onboarding_path = self.soul_dir / "onboarding.json"
        self.trash_dir = self.soul_dir / ".trash"
        self.migration_marker_path = self.soul_dir / ".migration-v2.json"

    def initialize(self) -> None:
        for directory in (
            self.profile_dir,
            self.voice_dir,
            self.daily_dir,
            self.memory_db_dir,
            self.candidates_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def migrate_legacy(
        self,
        *,
        legacy_soul: Path | None = None,
        legacy_conversation: Path | None = None,
        legacy_voice: Path | None = None,
        legacy_memory_db: Path | None = None,
        legacy_daily: Path | None = None,
        backup_name: str | None = None,
    ) -> MigrationResult:
        """Copy legacy data into the scoped layout after creating a backup.

        Existing scoped files win and legacy inputs are never removed.
        """
        self.initialize()
        stamp = backup_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = self.data_root / "backups" / stamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []

        mappings = [
            (legacy_soul, self.profile_dir, backup_dir / "soul"),
            (legacy_voice, self.voice_dir, backup_dir / "voice"),
            (legacy_memory_db, self.memory_db_dir, backup_dir / "memory_db"),
            (legacy_daily, self.daily_dir, backup_dir / "daily"),
        ]
        for source, destination, backup in mappings:
            if source is None or not Path(source).exists():
                continue
            source = Path(source)
            shutil.copytree(source, backup, dirs_exist_ok=True)
            for item in source.rglob("*"):
                if not item.is_file():
                    continue
                relative = item.relative_to(source)
                target = destination / relative
                if not target.exists():
                    _copy_file_atomic(item, target)
                    copied.append(target)

        if legacy_conversation is not None and Path(legacy_conversation).exists():
            source = Path(legacy_conversation)
            shutil.copy2(source, backup_dir / "conversation.json")
            if not self.conversation_path.exists():
                _copy_file_atomic(source, self.conversation_path)
                copied.append(self.conversation_path)

        manifest = {
            "soul_id": self.soul_id,
            "copied": [str(path.relative_to(self.data_root)) for path in copied],
            "sha256": {
                str(path.relative_to(self.data_root)): _sha256(path)
                for path in copied
            },
            "legacy_preserved": True,
        }
        payload = json.dumps(manifest, ensure_ascii=False, indent=2)
        atomic_write_text(backup_dir / "migration.json", payload)
        atomic_write_text(
            self.migration_marker_path,
            json.dumps(
                {**manifest, "backup": str(backup_dir.relative_to(self.data_root))},
                ensure_ascii=False,
                indent=2,
            ),
        )
        return MigrationResult(backup_dir=backup_dir, copied=tuple(copied))

    def archive_chat(self, archive_name: str | None = None) -> Path:
        """Move conversation artifacts into a recoverable per-Soul trash folder."""
        stamp = archive_name or datetime.now(timezone.utc).strftime("chat-%Y%m%dT%H%M%SZ")
        if not stamp or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in stamp):
            raise ValueError("archive name contains unsupported characters")
        destination = self.trash_dir / stamp
        suffix = 1
        while destination.exists():
            destination = self.trash_dir / f"{stamp}-{suffix}"
            suffix += 1
        destination.mkdir(parents=True)

        if self.conversation_path.exists():
            shutil.move(str(self.conversation_path), destination / "conversation.json")
        if self.daily_dir.exists() and any(self.daily_dir.iterdir()):
            shutil.move(str(self.daily_dir), destination / "daily")
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_file_atomic(source: Path, destination: Path) -> None:
    """Copy one legacy file without exposing a partially written destination."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source, temp_path)
        if _sha256(source) != _sha256(temp_path):
            raise OSError(f"copy verification failed: {source}")
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)
