import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.7


@dataclass
class MiniMaxConfig:
    base_url: str = "https://api.minimaxi.com"
    api_key: str = ""
    model: str = "speech-2.8-hd"


@dataclass
class VoiceProviderConfig:
    provider: Literal["local", "minimax"] = "local"
    minimax: MiniMaxConfig = field(default_factory=MiniMaxConfig)
    auto_play: bool = False
    audio_cache_size: int = 10


@dataclass
class AppConfig:
    # === 全局 ===
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: VoiceProviderConfig = field(default_factory=VoiceProviderConfig)
    soul_path: str = "config/souls/demo"
    soul_id: str = "default"
    data_root: str = "data"
    frontend_origin: str = "http://localhost:3326"

    # === Pipeline 模块 ===
    crunch_interval: int = 10           # 上下文压缩 & 人物信息提取的触发间隔（轮）
    compress_keep_recent: int = 6       # 压缩时保留的最近消息条数
    max_conversation_turns: int = 20    # 对话轮数上限，超出自动截断旧消息
    max_regenerate: int = 2             # 质量检查不合格时的最大重生成次数

    # === 蒸馏模块 ===
    distill_max_retries: int = 2        # 蒸馏 LLM 调用失败时的最大重试次数


class ConfigLoader:
    """JSON 配置加载器，从 config/ 目录加载所有配置"""

    def __init__(self, config_dir: Path):
        self._config_dir = Path(config_dir)

    def load(self) -> AppConfig:
        config = AppConfig()

        llm_path = self._config_dir / "llm.json"
        if llm_path.exists():
            llm_data = json.loads(llm_path.read_text())
            config.llm = LLMConfig(**llm_data)

        tts_path = self._config_dir / "tts.json"
        if tts_path.exists():
            tts_data = json.loads(tts_path.read_text())
            provider = tts_data.get("provider", config.tts.provider)
            if provider not in ("local", "minimax"):
                raise ValueError("不支持的语音服务")

            minimax_data = tts_data.get("minimax", {})
            config.tts = VoiceProviderConfig(
                provider=provider,
                auto_play=tts_data.get("auto_play", False) is True,
                audio_cache_size=max(0, min(100, int(tts_data.get("audio_cache_size", 10)))),
                minimax=MiniMaxConfig(
                    base_url=minimax_data.get("base_url", config.tts.minimax.base_url),
                    api_key=minimax_data.get("api_key", config.tts.minimax.api_key),
                    model=minimax_data.get("model", config.tts.minimax.model),
                ),
            )

        app_path = self._config_dir / "app.json"
        if app_path.exists():
            app_data = json.loads(app_path.read_text())
            config.soul_path = app_data.get("soul_path", config.soul_path)
            config.soul_id = app_data.get("soul_id", config.soul_id)
            config.data_root = app_data.get("data_root", config.data_root)
            config.frontend_origin = app_data.get("frontend_origin", config.frontend_origin)

            pipeline = app_data.get("pipeline", {})
            config.crunch_interval = pipeline.get("crunch_interval", config.crunch_interval)
            config.compress_keep_recent = pipeline.get("compress_keep_recent", config.compress_keep_recent)
            config.max_conversation_turns = pipeline.get("max_conversation_turns", config.max_conversation_turns)
            config.max_regenerate = pipeline.get("max_regenerate", config.max_regenerate)

            distill = app_data.get("distill", {})
            config.distill_max_retries = distill.get("max_retries", config.distill_max_retries)

        return config
