import json
import threading
from copy import deepcopy
from pathlib import Path
from .loader import ConfigLoader, AppConfig
from ..data.files import atomic_write_text


class Settings:
    """配置单例，统一管理所有模块的配置"""

    _instance: "Settings | None" = None

    def __init__(self, config_dir: Path):
        self._config_dir = Path(config_dir)
        self._loader = ConfigLoader(self._config_dir)
        self._config: AppConfig = self._loader.load()
        self._write_lock = threading.RLock()
        self._circumstances: str = ""
        self._log_level: str = "error"
        self._load_circumstances()
        self._load_log_level()

    @classmethod
    def init(cls, config_dir: Path) -> "Settings":
        """初始化单例"""
        cls._instance = cls(config_dir)
        return cls._instance

    @classmethod
    def get(cls) -> "Settings":
        """获取单例实例"""
        if cls._instance is None:
            raise RuntimeError("Settings not initialized. Call Settings.init() first.")
        return cls._instance

    @property
    def llm(self):
        return self._config.llm

    @property
    def tts(self):
        return self._config.tts

    @property
    def soul_path(self) -> Path:
        return self._config_dir.parent / self._config.soul_path

    @property
    def data_dir(self) -> Path:
        return self._config_dir

    @property
    def soul_id(self) -> str:
        return self._config.soul_id

    @property
    def data_root(self) -> Path:
        return self._config_dir.parent / self._config.data_root

    @property
    def circumstances(self) -> str:
        return self._circumstances

    @property
    def frontend_origin(self) -> str:
        return self._config.frontend_origin

    @property
    def crunch_interval(self) -> int:
        return self._config.crunch_interval

    @property
    def compress_keep_recent(self) -> int:
        return self._config.compress_keep_recent

    @property
    def max_conversation_turns(self) -> int:
        return self._config.max_conversation_turns

    @property
    def max_regenerate(self) -> int:
        return self._config.max_regenerate

    @property
    def distill_max_retries(self) -> int:
        return self._config.distill_max_retries

    @property
    def log_level(self) -> str:
        return self._log_level

    def update_log_level(self, level: str):
        """更新日志等级并写回 app.json"""
        self._log_level = level
        from .logger import set_level
        set_level(level)
        self._save_app_json()

    def _load_log_level(self):
        """从 app.json 加载日志等级"""
        app_path = self._config_dir / "app.json"
        if app_path.exists():
            import json
            data = json.loads(app_path.read_text())
            self._log_level = data.get("log_level", "error")

    def _load_circumstances(self):
        path = self._config_dir / "circumstances.md"
        if path.exists():
            self._circumstances = path.read_text()

    def update_llm(self, provider=None, cloud=None, ollama=None, **legacy):
        """更新 LLM 配置并写回 JSON 文件"""
        with self._write_lock:
            candidate = deepcopy(self._config.llm)
            if provider is not None:
                candidate.provider = provider
            if candidate.provider not in ("cloud", "local"):
                raise ValueError("不支持的对话服务")
            cloud_update = {**legacy, **(cloud or {})}
            for key, value in cloud_update.items():
                if key == "api_key" and value in (None, "***"):
                    continue
                if value is not None and key in ("base_url", "api_key", "model", "temperature"):
                    setattr(candidate.cloud, key, value)
            for key, value in (ollama or {}).items():
                if value is not None and key in ("base_url", "model", "temperature"):
                    setattr(candidate.ollama, key, value)
            self._save_json("llm.json", candidate)
            self._config.llm = candidate

    def update_tts(
        self,
        provider: str | None = None,
        minimax: dict[str, object] | None = None,
        openai_compatible: dict[str, object] | None = None,
        auto_play: bool | None = None,
        audio_cache_size: int | None = None,
    ) -> None:
        """更新 TTS 配置并写回 JSON 文件。"""
        with self._write_lock:
            candidate = deepcopy(self._config.tts)

            if provider is not None:
                candidate.provider = provider
            if auto_play is not None:
                candidate.auto_play = auto_play
            if audio_cache_size is not None:
                candidate.audio_cache_size = max(0, min(100, audio_cache_size))
            if candidate.provider not in ("local", "minimax", "openai_compatible"):
                raise ValueError("不支持的语音服务")

            if minimax is not None:
                for key in ("base_url", "api_key", "model"):
                    if key in minimax:
                        setattr(candidate.minimax, key, minimax[key])
            if openai_compatible is not None:
                for key in ("base_url", "api_key", "model", "voice"):
                    if key in openai_compatible:
                        setattr(candidate.openai_compatible, key, openai_compatible[key])

            self._save_json("tts.json", candidate)
            self._config.tts = candidate

    def update_circumstances(self, content: str):
        """更新场景描述并写回 circumstances.md"""
        self._circumstances = content
        path = self._config_dir / "circumstances.md"
        atomic_write_text(path, content)

    def _save_json(self, filename: str, dataclass_instance):
        from dataclasses import asdict
        path = self._config_dir / filename
        atomic_write_text(
            path,
            json.dumps(asdict(dataclass_instance), indent=2, ensure_ascii=False),
        )

    def _save_app_json(self):
        """保存 app.json 中的运行时设置"""
        path = self._config_dir / "app.json"
        data = {
            "soul_path": self._config.soul_path,
            "soul_id": self._config.soul_id,
            "data_root": self._config.data_root,
            "log_level": self._log_level,
            "frontend_origin": self._config.frontend_origin,
            "pipeline": {
                "crunch_interval": self._config.crunch_interval,
                "compress_keep_recent": self._config.compress_keep_recent,
                "max_conversation_turns": self._config.max_conversation_turns,
                "max_regenerate": self._config.max_regenerate,
            },
            "distill": {
                "max_retries": self._config.distill_max_retries,
            },
        }
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))
