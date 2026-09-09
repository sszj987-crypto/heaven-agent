from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


VALID_STATUSES = {"pending", "approved", "rejected"}


class CandidateNotFound(KeyError):
    pass


class CandidateStateError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryCandidate:
    id: str
    dimension: str
    content: str
    source_type: str
    source_excerpt: str
    confidence: float
    source_speaker: str = ""
    status: str = "pending"
    conflict_with: str | None = None
    created_at: str = ""
    resolved_at: str | None = None


class CandidateStore:
    def __init__(self, path: Path):
        self._path = Path(path)

    def add(
        self,
        *,
        dimension: str,
        content: str,
        source_type: str,
        source_excerpt: str,
        confidence: float,
        source_speaker: str = "",
        conflict_with: str | None = None,
    ) -> MemoryCandidate:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        candidate = MemoryCandidate(
            id=f"candidate_{uuid.uuid4().hex[:12]}",
            dimension=dimension,
            content=content.strip(),
            source_type=source_type,
            source_excerpt=source_excerpt.strip(),
            confidence=confidence,
            source_speaker=source_speaker.strip(),
            conflict_with=conflict_with,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        items = self._load()
        items.append(candidate)
        self._save(items)
        return candidate

    def list(self, status: str | None = None) -> list[MemoryCandidate]:
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"invalid candidate status: {status}")
        items = self._load()
        return [item for item in items if status is None or item.status == status]

    def resolve(
        self, candidate_id: str, status: str, edited_content: str | None = None
    ) -> MemoryCandidate:
        if status not in {"approved", "rejected"}:
            raise ValueError("resolution must be approved or rejected")
        items = self._load()
        updated: MemoryCandidate | None = None
        result: list[MemoryCandidate] = []
        for item in items:
            if item.id != candidate_id:
                result.append(item)
                continue
            if item.status != "pending":
                raise CandidateStateError(
                    f"candidate {candidate_id} is already {item.status}"
                )
            updated = MemoryCandidate(
                **{
                    **asdict(item),
                    "content": edited_content.strip() if edited_content else item.content,
                    "status": status,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            result.append(updated)
        if updated is None:
            raise CandidateNotFound(candidate_id)
        self._save(result)
        return updated

    def extract_by_source_type(self, source_type: str) -> list[MemoryCandidate]:
        """Remove and return candidates whose private provenance belongs to a source."""
        items = self._load()
        extracted = [item for item in items if item.source_type == source_type]
        if extracted:
            self._save([item for item in items if item.source_type != source_type])
        return extracted

    def _load(self) -> list[MemoryCandidate]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read candidate store: {self._path}") from exc
        return [MemoryCandidate(**item) for item in raw]

    def _save(self, items: list[MemoryCandidate]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=".candidates-", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
