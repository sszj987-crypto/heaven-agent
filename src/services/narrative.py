"""Deterministic policy for sensitive memorial and afterlife narratives."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class NarrativeDecision:
    afterlife_topic_allowed: bool


class NarrativePolicy:
    """Gate persona self-claims about death or an afterlife by user intent."""

    _INPUT_TRIGGERS = tuple(
        re.compile(pattern)
        for pattern in (
            r"(?:你|您).{0,8}(?:去世|离世|过世|死后|死了|走了以后|不在了)",
            r"(?:去世|离世|过世|死后|走了以后|不在了).{0,8}(?:你|您)",
            r"(?:你|您).{0,8}(?:天堂|来世|另一个世界|另一个地方|那边)",
            r"(?:天堂|来世|另一个世界|另一个地方|那边).{0,8}(?:你|您)",
            r"在那边.{0,6}(?:好吗|怎么样|过得)",
        )
    )

    _SELF_CONTEXT_MARKERS = (
        "离世年份",
        "去世年份",
        "我已去世",
        "我已经去世",
        "我已离世",
        "我已经离世",
        "我已经不在人世",
        "我已不在人世",
        "目前在天堂",
        "身处天堂",
    )

    _OUTPUT_VIOLATIONS = (
        (
            "self_afterlife_location",
            re.compile(
                r"(?:我|咱).{0,8}(?:在|住在|待在)(?:这边|那边|天堂|来世|另一个世界|另一个地方)"
            ),
        ),
        (
            "afterlife_wellbeing",
            re.compile(r"(?:这边|那边|天堂).{0,8}(?:挺好|很好|还好|安好|过得不错)"),
        ),
        (
            "self_deceased_claim",
            re.compile(r"(?:我|咱).{0,6}(?:已经|早就|现在)?(?:去世|离世|死了|不在人世)"),
        ),
    )

    _SAFE_FALLBACK = "看到你的消息啦。最近怎么样？"

    def evaluate(self, user_message: str) -> NarrativeDecision:
        normalized = re.sub(r"\s+", "", user_message)
        return NarrativeDecision(
            afterlife_topic_allowed=any(
                pattern.search(normalized) for pattern in self._INPUT_TRIGGERS
            )
        )

    def output_violation(self, reply: str, *, afterlife_topic_allowed: bool) -> str | None:
        if afterlife_topic_allowed:
            return None
        normalized = re.sub(r"\s+", "", reply)
        for code, pattern in self._OUTPUT_VIOLATIONS:
            if pattern.search(normalized):
                return code
        return None

    def redact_profile_text(self, text: str, *, afterlife_topic_allowed: bool) -> str:
        """Remove persona self-death lines while preserving relatives' life events."""
        if afterlife_topic_allowed or not text:
            return text
        return "\n".join(
            line
            for line in text.splitlines()
            if not any(marker in line for marker in self._SELF_CONTEXT_MARKERS)
        ).strip()

    def contains_sensitive_scene(self, text: str) -> bool:
        return any(
            marker in text
            for marker in (*self._SELF_CONTEXT_MARKERS, "所在之地: 天堂", "所在之地：天堂")
        )

    @property
    def safe_fallback(self) -> str:
        return self._SAFE_FALLBACK
