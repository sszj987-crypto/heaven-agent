from __future__ import annotations

import json

from ..memory.candidates import CandidateStore, MemoryCandidate


class ImportReviewService:
    """把导入分析结果转换为待人工确认的候选项。"""

    def __init__(self, store: CandidateStore, excerpt_limit: int = 1_000):
        self._store = store
        self._excerpt_limit = excerpt_limit

    def queue(self, result, raw_text: str) -> list[MemoryCandidate]:
        excerpt = raw_text.strip()[: self._excerpt_limit]
        queued = [
            self._store.add(
                dimension=dimension,
                content=result.profile[dimension],
                source_type="import_dimension",
                source_excerpt=excerpt,
                confidence=0.9,
            )
            for dimension in result.changes
            if result.profile.get(dimension, "").strip()
        ]
        skill = result.skill_card
        if skill is not None and skill.has_content:
            queued.append(
                self._store.add(
                    dimension="skill",
                    content=json.dumps(skill.to_dict(), ensure_ascii=False),
                    source_type="import_skill",
                    source_excerpt=excerpt,
                    confidence=0.85,
                )
            )
        return queued
