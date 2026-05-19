import json
import tempfile
from pathlib import Path
from src.config.loader import ConfigLoader, AppConfig, LLMConfig, VoiceConfig


class TestConfigLoader:
    def test_load_empty_dir_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.base_url == "https://api.openai.com/v1"
            assert config.llm.api_key == ""
            assert config.llm.model == "gpt-4o"
            assert config.voice.fish_speech_url == "http://localhost:8080"
            assert config.soul_path == "config/souls/demo"

    def test_load_llm_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            llm_data = {"base_url": "https://custom.api.com/v1", "api_key": "sk-test", "model": "gpt-4o-mini"}
            (Path(tmp) / "llm.json").write_text(json.dumps(llm_data))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.base_url == "https://custom.api.com/v1"
            assert config.llm.api_key == "sk-test"
            assert config.llm.model == "gpt-4o-mini"

    def test_load_voice_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            voice_data = {"fish_speech_url": "http://192.168.1.100:8080"}
            (Path(tmp) / "voice.json").write_text(json.dumps(voice_data))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.voice.fish_speech_url == "http://192.168.1.100:8080"

    def test_load_app_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_data = {"soul_path": "config/souls/my_soul"}
            (Path(tmp) / "app.json").write_text(json.dumps(app_data))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.soul_path == "config/souls/my_soul"

    def test_load_all_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "llm.json").write_text(json.dumps({"model": "claude-4"}))
            (Path(tmp) / "voice.json").write_text(json.dumps({"fish_speech_url": "http://localhost:9999"}))
            (Path(tmp) / "app.json").write_text(json.dumps({"soul_path": "custom/soul"}))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.model == "claude-4"
            assert config.voice.fish_speech_url == "http://localhost:9999"
            assert config.soul_path == "custom/soul"

    def test_partial_llm_config_fills_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "llm.json").write_text(json.dumps({"model": "gemini-pro"}))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.model == "gemini-pro"
            assert config.llm.base_url == "https://api.openai.com/v1"  # default
            assert config.llm.api_key == ""  # default
