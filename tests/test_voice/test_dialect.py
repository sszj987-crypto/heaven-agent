from src.voice.dialect import DialectConfig, DialectSettings


def test_default_dialect_is_mandarin_without_a_saved_file(tmp_path):
    config = DialectSettings(tmp_path / "voice" / "dialect.json").load()

    assert config == DialectConfig(enabled=False, dialect_id="mandarin")
    assert config.tts_instruction == ""
    assert config.asr_language_hint is None


def test_cantonese_dialect_persists_all_shared_hints(tmp_path):
    store = DialectSettings(tmp_path / "voice" / "dialect.json")
    store.save(DialectConfig(enabled=True, dialect_id="cantonese"))

    config = store.load()
    assert config.enabled is True
    assert config.dialect_id == "cantonese"
    assert "繁体粤语口语" in config.text_instruction
    assert "粤语口音" in config.tts_instruction
    assert config.asr_language_hint == "zh"
    assert "粤语对话" in config.asr_initial_prompt


def test_disabling_dialect_normalizes_to_mandarin(tmp_path):
    store = DialectSettings(tmp_path / "voice" / "dialect.json")
    saved = store.save(DialectConfig(enabled=False, dialect_id="cantonese"))

    assert saved == DialectConfig(enabled=False, dialect_id="mandarin")
    assert store.load() == saved
