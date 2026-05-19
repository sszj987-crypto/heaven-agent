import json
import tempfile
from pathlib import Path
from src.config.settings import Settings


class TestSettings:
    def setup_method(self):
        """每个测试前重置单例"""
        Settings._instance = None

        self._tmp = tempfile.TemporaryDirectory()
        self._config_dir = Path(self._tmp.name)

        # 写入基础配置文件
        (self._config_dir / "llm.json").write_text(json.dumps({
            "base_url": "https://api.test.com/v1",
            "api_key": "sk-test123",
            "model": "gpt-4o",
        }))
        (self._config_dir / "voice.json").write_text(json.dumps({
            "fish_speech_url": "http://localhost:8080",
        }))
        (self._config_dir / "app.json").write_text(json.dumps({
            "soul_path": "config/souls/demo",
        }))

    def teardown_method(self):
        self._tmp.cleanup()

    def test_init_and_get(self):
        Settings.init(self._config_dir)
        settings = Settings.get()

        assert settings.llm.model == "gpt-4o"
        assert settings.llm.api_key == "sk-test123"

    def test_get_before_init_raises(self):
        Settings._instance = None
        try:
            Settings.get()
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass

    def test_singleton_behavior(self):
        s1 = Settings.init(self._config_dir)
        s2 = Settings.get()
        assert s1 is s2

    def test_llm_property(self):
        Settings.init(self._config_dir)
        llm = Settings.get().llm
        assert llm.base_url == "https://api.test.com/v1"
        assert llm.model == "gpt-4o"

    def test_voice_property(self):
        Settings.init(self._config_dir)
        voice = Settings.get().voice
        assert voice.fish_speech_url == "http://localhost:8080"

    def test_soul_path(self):
        Settings.init(self._config_dir)
        assert Settings.get().soul_path.name == "demo"

    def test_circumstances_loads_from_file(self):
        (self._config_dir / "circumstances.md").write_text("# 场景\n用户正在思念奶奶。")
        Settings.init(self._config_dir)
        assert "思念奶奶" in Settings.get().circumstances

    def test_circumstances_empty_when_no_file(self):
        Settings.init(self._config_dir)
        assert Settings.get().circumstances == ""

    def test_update_llm_writes_back(self):
        Settings.init(self._config_dir)
        Settings.get().update_llm(api_key="new-key", model="gpt-4o-mini")

        # 验证内存
        assert Settings.get().llm.api_key == "new-key"
        assert Settings.get().llm.model == "gpt-4o-mini"

        # 验证写回文件
        saved = json.loads((self._config_dir / "llm.json").read_text())
        assert saved["api_key"] == "new-key"
        assert saved["model"] == "gpt-4o-mini"

    def test_update_voice_writes_back(self):
        Settings.init(self._config_dir)
        Settings.get().update_voice(fish_speech_url="http://new-url:8080")

        assert Settings.get().voice.fish_speech_url == "http://new-url:8080"
        saved = json.loads((self._config_dir / "voice.json").read_text())
        assert saved["fish_speech_url"] == "http://new-url:8080"
