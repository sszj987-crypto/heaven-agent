from dataclasses import dataclass, field


@dataclass
class EmotionTag:
    """情绪标签"""
    type: str = "neutral"  # grief / guilt / longing / joy / anxiety / neutral
    intensity: float = 0.3
    is_high_intensity: bool = False


@dataclass
class TTSConfig:
    """TTS 精细控制参数"""
    emotion: str = "neutral"   # gentle / happy / sad / calm / neutral
    speed: float = 1.0         # 0.5-2.0
    pitch: int = 0             # -12 到 +12
    pause_ms: int = 300        # 句间停顿 (ms)


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

    # LLM 产出
    response: str = ""
    need_regenerate: bool = False

    # Postprocess 产出
    tts_config: TTSConfig | None = None
