import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LLMEndpointConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.7


@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = ""
    temperature: float = 0.7


@dataclass(init=False)
class LLMConfig:
    provider: Literal["cloud", "local"]
    cloud: LLMEndpointConfig
    ollama: OllamaConfig

    def __init__(
        self,
        provider: Literal["cloud", "local"] = "cloud",
        cloud: LLMEndpointConfig | None = None,
        ollama: OllamaConfig | None = None,
        # Kept for callers that construct the formerly-flat configuration.
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ):
        self.provider = provider
        self.cloud = cloud or LLMEndpointConfig()
        self.ollama = ollama or OllamaConfig()
        for key, value in (("base_url", base_url), ("api_key", api_key), ("model", model), ("temperature", temperature)):
            if value is not None:
                setattr(self.cloud, key, value)

    @property
    def active(self) -> LLMEndpointConfig:
        if self.provider == "local":
            # Ollama ignores this value, but its OpenAI-compatible clients expect one.
            return LLMEndpointConfig(
                base_url=self.ollama.base_url,
                api_key="ollama",
                model=self.ollama.model,
                temperature=self.ollama.temperature,
            )
        return self.cloud

    # Transitional aliases keep internal integrations with the previous flat
    # cloud shape working while persisted settings use provider-specific fields.
    @property
    def base_url(self) -> str:
        return self.cloud.base_url

    @base_url.setter
    def base_url(self, value: str) -> None:
        self.cloud.base_url = value

    @property
    def api_key(self) -> str:
        return self.cloud.api_key

    @api_key.setter
    def api_key(self, value: str) -> None:
        self.cloud.api_key = value

    @property
    def model(self) -> str:
        return self.cloud.model

    @model.setter
    def model(self, value: str) -> None:
        self.cloud.model = value

    @property
    def temperature(self) -> float:
        return self.cloud.temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self.cloud.temperature = value


@dataclass
class MiniMaxConfig:
    base_url: str = "https://api.minimaxi.com"
    api_key: str = ""
    model: str = "speech-2.8-hd"


@dataclass
class OpenAICompatibleTTSConfig:
    """Configuration shared by OpenAI and OpenAI-format TTS gateways."""

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini-tts"
    voice: str = "alloy"


@dataclass
class VoiceProviderConfig:
    provider: Literal["local", "minimax", "openai_compatible"] = "local"
    minimax: MiniMaxConfig = field(default_factory=MiniMaxConfig)
    openai_compatible: OpenAICompatibleTTSConfig = field(
        default_factory=OpenAICompatibleTTSConfig
    )
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
            # Pre-provider versions stored one flat OpenAI-compatible service.
            if "provider" not in llm_data and "cloud" not in llm_data:
                config.llm = LLMConfig(cloud=LLMEndpointConfig(**llm_data))
            else:
                provider = llm_data.get("provider", "cloud")
                if provider not in ("cloud", "local"):
                    raise ValueError("不支持的对话服务")
                cloud_data = llm_data.get("cloud", {})
                ollama_data = llm_data.get("ollama", {})
                config.llm = LLMConfig(
                    provider=provider,
                    cloud=LLMEndpointConfig(
                        base_url=cloud_data.get("base_url", config.llm.cloud.base_url),
                        api_key=cloud_data.get("api_key", config.llm.cloud.api_key),
                        model=cloud_data.get("model", config.llm.cloud.model),
                        temperature=cloud_data.get("temperature", config.llm.cloud.temperature),
                    ),
                    ollama=OllamaConfig(
                        base_url=ollama_data.get("base_url", config.llm.ollama.base_url),
                        model=ollama_data.get("model", config.llm.ollama.model),
                        temperature=ollama_data.get("temperature", config.llm.ollama.temperature),
                    ),
                )

        tts_path = self._config_dir / "tts.json"
        if tts_path.exists():
            tts_data = json.loads(tts_path.read_text())
            provider = tts_data.get("provider", config.tts.provider)
            if provider not in ("local", "minimax", "openai_compatible"):
                raise ValueError("不支持的语音服务")

            minimax_data = tts_data.get("minimax", {})
            openai_data = tts_data.get("openai_compatible", {})
            config.tts = VoiceProviderConfig(
                provider=provider,
                auto_play=tts_data.get("auto_play", False) is True,
                audio_cache_size=max(0, min(100, int(tts_data.get("audio_cache_size", 10)))),
                minimax=MiniMaxConfig(
                    base_url=minimax_data.get("base_url", config.tts.minimax.base_url),
                    api_key=minimax_data.get("api_key", config.tts.minimax.api_key),
                    model=minimax_data.get("model", config.tts.minimax.model),
                ),
                openai_compatible=OpenAICompatibleTTSConfig(
                    base_url=openai_data.get(
                        "base_url", config.tts.openai_compatible.base_url
                    ),
                    api_key=openai_data.get(
                        "api_key", config.tts.openai_compatible.api_key
                    ),
                    model=openai_data.get(
                        "model", config.tts.openai_compatible.model
                    ),
                    voice=openai_data.get(
                        "voice", config.tts.openai_compatible.voice
                    ),
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
