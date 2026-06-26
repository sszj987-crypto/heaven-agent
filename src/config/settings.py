import json
from pathlib import Path
from .loader import ConfigLoader, AppConfig


class Settings:
    """配置单例，统一管理所有模块的配置"""

    _instance: "Settings | None" = None

    def __init__(self, config_dir: Path):
        self._config_dir = Path(config_dir)
        self._loader = ConfigLoader(self._config_dir)
        self._config: AppConfig = self._loader.load()
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
    def soul_path(self) -> Path:
        return self._config_dir.parent / self._config.soul_path

    @property
    def data_dir(self) -> Path:
        return self._config_dir

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

    def update_llm(self, **kwargs):
        """更新 LLM 配置并写回 JSON 文件"""
        for key, value in kwargs.items():
            if hasattr(self._config.llm, key):
                setattr(self._config.llm, key, value)
        self._save_json("llm.json", self._config.llm)

    def update_circumstances(self, content: str):
        """更新场景描述并写回 circumstances.md"""
        self._circumstances = content
        path = self._config_dir / "circumstances.md"
        path.write_text(content)

    def _save_json(self, filename: str, dataclass_instance):
        from dataclasses import asdict
        path = self._config_dir / filename
        path.write_text(json.dumps(asdict(dataclass_instance), indent=2, ensure_ascii=False))

    def _save_app_json(self):
        """保存 app.json 中的运行时设置"""
        path = self._config_dir / "app.json"
        data = {
            "soul_path": self._config.soul_path,
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
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
