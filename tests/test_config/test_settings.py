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
        (self._config_dir / "app.json").write_text(json.dumps({
            "soul_path": "config/souls/demo",
        }))

    def teardown_method(self):
        self._tmp.cleanup()

    def _write_tts(self, **minimax):
        values = {
            "base_url": "https://api.minimaxi.com",
            "api_key": "",
            "model": "speech-2.8-hd",
        }
        values.update(minimax)
        (self._config_dir / "tts.json").write_text(json.dumps({
            "provider": "local",
            "minimax": values,
        }))

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

    def test_masked_api_key_does_not_overwrite_saved_secret(self):
        Settings.init(self._config_dir)

        Settings.get().update_llm(api_key="***", model="gpt-4o-mini")

        assert Settings.get().llm.api_key == "sk-test123"
        saved = json.loads((self._config_dir / "llm.json").read_text())
        assert saved["api_key"] == "sk-test123"

    def test_update_tts_keeps_secret_when_key_is_omitted(self):
        self._write_tts(api_key="existing")
        settings = Settings.init(self._config_dir)

        settings.update_tts(provider="minimax", minimax={"model": "speech-2.8-turbo"})

        assert settings.tts.minimax.api_key == "existing"

    def test_update_tts_empty_key_clears_secret(self):
        self._write_tts(api_key="existing")
        settings = Settings.init(self._config_dir)

        settings.update_tts(minimax={"api_key": ""})

        assert settings.tts.minimax.api_key == ""

    def test_voice_auto_play_defaults_off_and_survives_reload(self):
        self._write_tts(api_key="existing")
        settings = Settings(self._config_dir)
        assert settings.tts.auto_play is False
        settings.update_tts(auto_play=True)
        assert Settings(self._config_dir).tts.auto_play is True
        settings.update_tts(minimax={"model": "another-model"})
        assert Settings(self._config_dir).tts.auto_play is True
        settings.update_tts(auto_play=False)
        reloaded = Settings(self._config_dir)
        assert reloaded.tts.auto_play is False
        assert reloaded.tts.minimax.api_key == "existing"

    def test_update_circumstances_writes_back(self):
        Settings.init(self._config_dir)
        Settings.get().update_circumstances("新场景")
        assert Settings.get().circumstances == "新场景"
        saved = (self._config_dir / "circumstances.md").read_text()
        assert saved == "新场景"
