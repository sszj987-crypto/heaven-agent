from __future__ import annotations

import json
import threading
from collections.abc import Callable

from ..memory.candidates import CandidateStateError, CandidateStore, MemoryCandidate
from ..soul.skill_card import SkillCard


class CandidateService:
    def __init__(self, store: CandidateStore, soul_loader, invalidate_prompt: Callable[[], None]):
        self._store = store
        self._loader = soul_loader
        self._invalidate_prompt = invalidate_prompt
        self._lock = threading.RLock()

    def list(self, status: str | None = "pending") -> list[MemoryCandidate]:
        return self._store.list(status)

    def approve(self, candidate_id: str, edited_content: str | None = None) -> MemoryCandidate:
        with self._lock:
            original = next(
                (item for item in self._store.list(None) if item.id == candidate_id),
                None,
            )
            if original is None:
                from ..memory.candidates import CandidateNotFound
                raise CandidateNotFound(candidate_id)
            if original.status != "pending":
                raise CandidateStateError(
                    f"candidate {candidate_id} is already {original.status}"
                )

            content = edited_content.strip() if edited_content else original.content
            skill: SkillCard | None = None
            if original.source_type == "import_skill":
                try:
                    skill = SkillCard.from_dict(json.loads(content))
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("行为规则候选内容不是有效 JSON") from exc

            # Persist the reviewed fact before advancing the inbox state. A disk
            # failure must remain retryable instead of stranding an approved item.
            if original.source_type == "import_skill":
                self._loader.save_skill(skill)
            elif original.source_type == "import_dimension":
                self._loader.save_dimension(original.dimension, content)
            else:
                current = self._loader.load_dimension(original.dimension).rstrip()
                entry = f"- {content}"
                already_persisted = any(
                    line.strip() == entry for line in current.splitlines()
                )
                if not already_persisted:
                    updated = f"{current}\n{entry}\n" if current else f"{entry}\n"
                    self._loader.save_dimension(original.dimension, updated)

            candidate = self._store.resolve(candidate_id, "approved", edited_content)
            self._invalidate_prompt()
            return candidate

    def reject(self, candidate_id: str) -> MemoryCandidate:
        with self._lock:
            return self._store.resolve(candidate_id, "rejected")
