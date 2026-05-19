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
        self._load_circumstances()

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
    def voice(self):
        return self._config.voice

    @property
    def soul_path(self) -> Path:
        return self._config_dir.parent / self._config.soul_path

    @property
    def circumstances(self) -> str:
        return self._circumstances

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

    def update_voice(self, **kwargs):
        """更新 Voice 配置并写回 JSON 文件"""
        for key, value in kwargs.items():
            if hasattr(self._config.voice, key):
                setattr(self._config.voice, key, value)
        self._save_json("voice.json", self._config.voice)

    def _save_json(self, filename: str, dataclass_instance):
        from dataclasses import asdict
        path = self._config_dir / filename
        path.write_text(json.dumps(asdict(dataclass_instance), indent=2, ensure_ascii=False))
