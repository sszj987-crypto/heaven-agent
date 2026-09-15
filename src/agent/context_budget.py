"""Deterministic request-time context budgeting without mutating stored history."""

from __future__ import annotations

from dataclasses import dataclass


_COMPACTION_MARKER = "\n\n【中间资料因上下文预算已省略】\n\n"


@dataclass(frozen=True)
class ContextBudgetStats:
    max_chars: int
    input_chars: int
    output_chars: int
    system_compacted: bool
    dropped_history_messages: int
    dropped_history_chars: int
    overflow_chars: int


@dataclass(frozen=True)
class ContextBudgetResult:
    messages: list[dict]
    stats: ContextBudgetStats


class ContextBudgeter:
    """Keep mandatory turn context and admit history by semantic priority."""

    def __init__(self, max_chars: int = 24_000, system_share: float = 0.65):
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if not 0 < system_share <= 1:
            raise ValueError("system_share must be in (0, 1]")
        self.max_chars = max_chars
        self.system_share = system_share

    def build(
        self,
        *,
        system_prompt: str,
        history: list[dict],
        current_user: str,
        dialect_instruction: str = "",
    ) -> ContextBudgetResult:
        original_history = [dict(message) for message in history]
        input_chars = (
            len(system_prompt)
            + sum(len(str(message.get("content", ""))) for message in history)
            + len(dialect_instruction)
            + len(current_user)
        )

        tail_chars = len(dialect_instruction) + len(current_user)
        available_for_system_and_history = self.max_chars - tail_chars
        if input_chars <= self.max_chars:
            # The share is a pressure policy, not a permanent quota. Do not
            # degrade a prompt that already fits the configured request budget.
            desired_system_chars = len(system_prompt)
        else:
            desired_system_chars = min(
                len(system_prompt),
                int(self.max_chars * self.system_share),
                max(available_for_system_and_history, 0),
            )
        if desired_system_chars >= len(_COMPACTION_MARKER) + 2:
            selected_system = self._compact_system(system_prompt, desired_system_chars)
        else:
            # An impossibly small budget must not silently remove safety/output rules.
            selected_system = system_prompt
        system_compacted = selected_system != system_prompt

        mandatory_chars = len(selected_system) + tail_chars
        remaining = max(self.max_chars - mandatory_chars, 0)
        selected_indices = self._select_history(original_history, remaining)
        selected_history = [
            message
            for index, message in enumerate(original_history)
            if index in selected_indices
        ]

        messages = [{"role": "system", "content": selected_system}]
        messages.extend(selected_history)
        if dialect_instruction:
            messages.append({"role": "system", "content": dialect_instruction})
        messages.append({"role": "user", "content": current_user})

        output_chars = sum(len(str(message["content"])) for message in messages)
        dropped = [
            message
            for index, message in enumerate(original_history)
            if index not in selected_indices
        ]
        stats = ContextBudgetStats(
            max_chars=self.max_chars,
            input_chars=input_chars,
            output_chars=output_chars,
            system_compacted=system_compacted,
            dropped_history_messages=len(dropped),
            dropped_history_chars=sum(len(str(message.get("content", ""))) for message in dropped),
            overflow_chars=max(output_chars - self.max_chars, 0),
        )
        return ContextBudgetResult(messages=messages, stats=stats)

    @staticmethod
    def _compact_system(system_prompt: str, max_chars: int) -> str:
        if len(system_prompt) <= max_chars:
            return system_prompt
        payload_chars = max_chars - len(_COMPACTION_MARKER)
        head_chars = int(payload_chars * 0.65)
        tail_chars = payload_chars - head_chars
        return (
            system_prompt[:head_chars]
            + _COMPACTION_MARKER
            + system_prompt[-tail_chars:]
        )

    @classmethod
    def _select_history(cls, history: list[dict], remaining: int) -> set[int]:
        dialogue_chunks: list[tuple[list[int], int]] = []
        summary_chunks: list[tuple[list[int], int]] = []
        index = 0
        while index < len(history):
            message = history[index]
            role = message.get("role")
            if role == "system":
                summary_chunks.append(([index], cls._message_chars(message)))
                index += 1
                continue
            if (
                role == "user"
                and index + 1 < len(history)
                and history[index + 1].get("role") == "assistant"
            ):
                indices = [index, index + 1]
                size = sum(cls._message_chars(history[item]) for item in indices)
                dialogue_chunks.append((indices, size))
                index += 2
                continue
            # Persisted history is expected to contain complete user/assistant turns.
            # Ignore malformed or half-written turns instead of sending an orphaned
            # message that can distort the current conversation.
            index += 1

        selected: set[int] = set()
        for indices, size in [*reversed(dialogue_chunks), *reversed(summary_chunks)]:
            if size <= remaining:
                selected.update(indices)
                remaining -= size
        return selected

    @staticmethod
    def _message_chars(message: dict) -> int:
        return len(str(message.get("content", "")))
