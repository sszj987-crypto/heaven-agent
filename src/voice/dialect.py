"""Per-Soul dialect preferences shared by text, TTS, and ASR."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config.logger import get_logger
from ..data.files import atomic_write_text

log = get_logger("voice.dialect")


@dataclass(frozen=True)
class DialectDefinition:
    id: str
    label: str
    description: str
    text_instruction: str
    tts_instruction: str
    asr_language_hint: str | None
    asr_initial_prompt: str | None


_DIALECTS: dict[str, DialectDefinition] = {
    "mandarin": DialectDefinition(
        id="mandarin",
        label="普通话",
        description="使用默认中文文字与普通话语音。",
        text_instruction="",
        tts_instruction="",
        asr_language_hint=None,
        asr_initial_prompt=None,
    ),
    "cantonese": DialectDefinition(
        id="cantonese",
        label="粤语",
        description="使用繁体粤语口语文字，并以自然粤语口音说话。",
        text_instruction=(
            "【方言模式：粤语】\n"
            "所有 reply 必须使用自然的繁体粤语口语，符合人物原有说话习惯。"
            "不要改用普通话书面语，也不要在同一句中混用普通话表达；"
            "仍须遵守所有关系、事实、安全和回复格式要求。"
        ),
        tts_instruction="请使用自然、清晰的粤语口音说话，保持人物原有音色与当前情绪语气。",
        # Whisper has a Chinese language token but no independent Cantonese token.
        asr_language_hint="zh",
        asr_initial_prompt="以下是粤语对话，请使用繁体粤语口语文字准确转写。",
    ),
}


@dataclass(frozen=True)
class DialectConfig:
    enabled: bool = False
    dialect_id: str = "mandarin"

    @property
    def definition(self) -> DialectDefinition:
        if self.enabled:
            return _DIALECTS.get(self.dialect_id, _DIALECTS["mandarin"])
        return _DIALECTS["mandarin"]

    @property
    def text_instruction(self) -> str:
        return self.definition.text_instruction

    @property
    def tts_instruction(self) -> str:
        return self.definition.tts_instruction

    @property
    def asr_language_hint(self) -> str | None:
        return self.definition.asr_language_hint

    @property
    def asr_initial_prompt(self) -> str | None:
        return self.definition.asr_initial_prompt


class DialectSettings:
    """Small durable store for a Soul's voice dialect mode."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> DialectConfig:
        if not self.path.exists():
            return DialectConfig()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            dialect_id = raw.get("dialect_id", "mandarin")
            enabled = bool(raw.get("enabled", False))
            if dialect_id not in _DIALECTS:
                raise ValueError(f"unknown dialect_id: {dialect_id}")
            if not enabled:
                dialect_id = "mandarin"
            return DialectConfig(enabled=enabled, dialect_id=dialect_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            log.warning("方言设置读取失败，已使用普通话默认值: %s", exc)
            return DialectConfig()

    def save(self, config: DialectConfig) -> DialectConfig:
        if config.dialect_id not in _DIALECTS:
            raise ValueError("不支持的方言模式")
        normalized = DialectConfig(
            enabled=config.enabled,
            dialect_id=config.dialect_id if config.enabled else "mandarin",
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.path,
            json.dumps(asdict(normalized), ensure_ascii=False, indent=2),
        )
        return normalized


def available_dialects() -> list[DialectDefinition]:
    return list(_DIALECTS.values())


def voice_supports_dialect_delivery(voice, provider: str) -> bool:
    """Only local MLX CosyVoice3 currently accepts our delivery instruction."""
    return provider == "local" and bool(getattr(voice, "supports_instruction", False))
