from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


FeedbackRating = Literal["similar", "dissimilar"]
FeedbackReason = Literal["fact", "style", "relationship", "response", "other"]
VALID_REASONS = frozenset({"fact", "style", "relationship", "response", "other"})


@dataclass(frozen=True)
class ReplyFeedback:
    response_id: str
    user_message: str
    response_text: str
    rating: FeedbackRating
    reasons: tuple[str, ...]
    suggestion: str = ""
    created_at: str = ""
    updated_at: str = ""


class FeedbackStore:
    """Local, per-Soul feedback store. Feedback never changes the persona itself."""

    def __init__(self, path: Path):
        self._path = Path(path)

    def upsert(
        self,
        *,
        response_id: str,
        user_message: str,
        response_text: str,
        rating: FeedbackRating,
        reasons: list[str] | tuple[str, ...] = (),
        suggestion: str = "",
    ) -> ReplyFeedback:
        if rating not in {"similar", "dissimilar"}:
            raise ValueError("invalid feedback rating")
        if not response_id.strip():
            raise ValueError("response_id is required")
        normalized_reasons = tuple(dict.fromkeys(reason.strip() for reason in reasons if reason.strip()))
        if not set(normalized_reasons) <= VALID_REASONS:
            raise ValueError("invalid feedback reason")
        if rating == "similar" and normalized_reasons:
            raise ValueError("similar feedback cannot include reasons")

        now = datetime.now(timezone.utc).isoformat()
        updated = ReplyFeedback(
            response_id=response_id.strip(),
            user_message=user_message.strip(),
            response_text=response_text.strip(),
            rating=rating,
            reasons=normalized_reasons,
            suggestion=suggestion.strip(),
            created_at=now,
            updated_at=now,
        )
        items = self._load()
        result: list[ReplyFeedback] = []
        found = False
        for item in items:
            if item.response_id != updated.response_id:
                result.append(item)
                continue
            result.append(ReplyFeedback(
                **{**asdict(updated), "created_at": item.created_at or now}
            ))
            found = True
        if not found:
            result.append(updated)
        self._save(result)
        return next(item for item in result if item.response_id == updated.response_id)

    def stats(self) -> dict:
        items = self._load()
        total = len(items)
        similar = sum(item.rating == "similar" for item in items)
        reasons = {reason: 0 for reason in sorted(VALID_REASONS)}
        for item in items:
            if item.rating == "dissimilar":
                for reason in item.reasons:
                    reasons[reason] += 1
        return {
            "total": total,
            "similar": similar,
            "dissimilar": total - similar,
            "similar_rate": similar / total if total else 0.0,
            "reasons": reasons,
        }

    def _load(self) -> list[ReplyFeedback]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read feedback store: {self._path}") from exc
        return [ReplyFeedback(**{**item, "reasons": tuple(item.get("reasons", ()))}) for item in raw]

    def _save(self, items: list[ReplyFeedback]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix=".feedback-", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self._path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
