import json
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    soul_path: str = "config/souls/demo"


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

        app_path = self._config_dir / "app.json"
        if app_path.exists():
            app_data = json.loads(app_path.read_text())
            config.soul_path = app_data.get("soul_path", config.soul_path)

        return config
