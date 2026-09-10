import json
import tempfile
from pathlib import Path
from src.config.loader import ConfigLoader, AppConfig, LLMConfig


class TestConfigLoader:
    def test_load_empty_dir_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.base_url == "https://api.openai.com/v1"
            assert config.llm.api_key == ""
            assert config.llm.model == "gpt-4o"
            assert config.soul_path == "config/souls/demo"
            assert config.soul_id == "default"
            assert config.data_root == "data"

    def test_load_llm_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            llm_data = {"base_url": "https://custom.api.com/v1", "api_key": "sk-test", "model": "gpt-4o-mini"}
            (Path(tmp) / "llm.json").write_text(json.dumps(llm_data))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.base_url == "https://custom.api.com/v1"
            assert config.llm.api_key == "sk-test"
            assert config.llm.model == "gpt-4o-mini"

    def test_load_app_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_data = {"soul_path": "config/souls/my_soul", "soul_id": "family", "data_root": "runtime"}
            (Path(tmp) / "app.json").write_text(json.dumps(app_data))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.soul_path == "config/souls/my_soul"
            assert config.soul_id == "family"
            assert config.data_root == "runtime"

    def test_load_all_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "llm.json").write_text(json.dumps({"model": "claude-4"}))
            (Path(tmp) / "app.json").write_text(json.dumps({"soul_path": "custom/soul"}))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.model == "claude-4"
            assert config.soul_path == "custom/soul"

    def test_partial_llm_config_fills_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "llm.json").write_text(json.dumps({"model": "gemini-pro"}))

            loader = ConfigLoader(Path(tmp))
            config = loader.load()

            assert config.llm.model == "gemini-pro"
            assert config.llm.base_url == "https://api.openai.com/v1"  # default
            assert config.llm.api_key == ""  # default

    def test_load_provider_llm_config_keeps_cloud_and_ollama_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "llm.json").write_text(json.dumps({
                "provider": "local",
                "cloud": {"base_url": "https://cloud.example/v1", "api_key": "secret", "model": "cloud-model"},
                "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen3:8b", "temperature": 0.2},
            }))
            config = ConfigLoader(Path(tmp)).load()

            assert config.llm.provider == "local"
            assert config.llm.cloud.model == "cloud-model"
            assert config.llm.ollama.model == "qwen3:8b"
            assert config.llm.active.api_key == "ollama"

    def test_tts_defaults_to_local_minimax_hd(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ConfigLoader(Path(tmp)).load()

            assert config.tts.provider == "local"
            assert config.tts.minimax.base_url == "https://api.minimaxi.com"
            assert config.tts.minimax.model == "speech-2.8-hd"
            assert config.tts.minimax.api_key == ""
            assert config.tts.openai_compatible.base_url == "https://api.openai.com/v1"
            assert config.tts.openai_compatible.model == "gpt-4o-mini-tts"
            assert config.tts.openai_compatible.voice == "alloy"

    def test_load_tts_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            (config_dir / "tts.json").write_text(json.dumps({
                "provider": "minimax",
                "minimax": {"api_key": "tts-secret", "model": "speech-2.8-turbo"},
            }))

            config = ConfigLoader(config_dir).load()

            assert config.tts.provider == "minimax"
            assert config.tts.minimax.api_key == "tts-secret"
            assert config.tts.minimax.model == "speech-2.8-turbo"

    def test_load_openai_compatible_tts_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            (config_dir / "tts.json").write_text(json.dumps({
                "provider": "openai_compatible",
                "openai_compatible": {
                    "base_url": "https://newapi.example/v1",
                    "api_key": "tts-secret",
                    "model": "custom-tts",
                    "voice": "voice_123",
                },
            }))

            config = ConfigLoader(config_dir).load()

            assert config.tts.provider == "openai_compatible"
            assert config.tts.openai_compatible.base_url == "https://newapi.example/v1"
            assert config.tts.openai_compatible.api_key == "tts-secret"
            assert config.tts.openai_compatible.voice == "voice_123"
