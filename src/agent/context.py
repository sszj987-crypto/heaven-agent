from dataclasses import dataclass, field


@dataclass
class EmotionTag:
    """情绪标签"""
    type: str = "neutral"  # grief / guilt / longing / joy / anxiety / neutral
    intensity: float = 0.3
    is_high_intensity: bool = False


@dataclass
class TTSConfig:
    """TTS 语音合成参数"""
    instruct_text: str = "用平静自然的语气说话。"


@dataclass
class PipelineContext:
    """Pipeline 上下文，在 preprocess → LLM → postprocess 链路中传递"""

    # 输入
    user_message: str = ""

    # Preprocess 产出
    soul_profile: object | None = None  # SoulProfile
    circumstances: str = ""
    emotion: EmotionTag | None = None
    system_prompt: str = ""
    llm_messages: list[dict] = field(default_factory=list)
    retrieved_memories: list[dict] = field(default_factory=list)  # MemoryRetrieveModule 产出

    # LLM 产出
    response: str = ""
    instruct_text: str = ""
    need_regenerate: bool = False
    safety_state: str = "normal"
