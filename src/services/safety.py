from dataclasses import dataclass
from typing import Literal


SafetyState = Literal["normal", "supportive_redirect", "crisis"]


@dataclass(frozen=True)
class SafetyDecision:
    state: SafetyState
    response: str | None = None


class SafetyPolicy:
    """Small deterministic guardrail for the local grief-companion flow."""

    _CRISIS = (
        "不想活", "自杀", "结束生命", "结束自己的生命", "去死", "活着没意义",
    )
    _SUPPORTIVE = (
        "很绝望", "撑不住", "活不下去", "没人能帮我", "崩溃",
    )

    def evaluate(self, text: str) -> SafetyDecision:
        normalized = text.replace(" ", "")
        if any(pattern in normalized for pattern in self._CRISIS):
            return SafetyDecision(
                state="crisis",
                response=(
                    "我很在意你此刻的安全。先不要独自承受，也先远离可能伤害自己的东西。"
                    "请现在联系一位现实中信任的人，让对方陪着你；如果你可能马上伤害自己，"
                    "请立即联系当地紧急服务或前往最近的急诊。这个 AI 不能替代现实中的专业帮助。"
                ),
            )
        if any(pattern in normalized for pattern in self._SUPPORTIVE):
            return SafetyDecision(state="supportive_redirect")
        return SafetyDecision(state="normal")
