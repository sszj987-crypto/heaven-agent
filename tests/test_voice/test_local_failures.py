import traceback

import pytest
from fastapi import HTTPException

from src.agent.context import TTSConfig
from src.api.chat_routes import _generate_audio
from src.services.container import voice_dependencies_available
from src.voice.tts import TTSService
from src.voice.tts_official import OfficialTTSService


def test_macos_missing_einops_is_reported_before_model_loading(tmp_path):
    model = tmp_path / "deps/Fun-CosyVoice3-0.5B-2512-8bit/model.safetensors"
    model.parent.mkdir(parents=True)
    model.touch()

    available, reason = voice_dependencies_available(
        "darwin", tmp_path,
        find_spec=lambda name: None if name == "einops" else object(),
    )

    assert not available
    assert "einops" in reason


@pytest.mark.parametrize("service_class", [TTSService, OfficialTTSService])
async def test_worker_failure_preserves_exception_and_traceback(
    tmp_path, monkeypatch, caplog, service_class,
):
    service = service_class(tmp_path)
    (tmp_path / "reference_audio.wav").touch()

    def fail_generation(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'einops'", name="einops")

    monkeypatch.setattr(service, "_generate", fail_generation)
    with pytest.raises(ModuleNotFoundError, match="einops"):
        _ = [chunk async for chunk in service.speak("你好")]

    record = next(r for r in caplog.records if "TTS 生成失败" in r.message)
    assert record.exc_info and record.exc_info[2] is not None
    assert "fail_generation" in "".join(traceback.format_exception(*record.exc_info))
    assert "NoneType: None" not in caplog.text


async def test_missing_runtime_dependency_returns_repair_action(tmp_path, monkeypatch):
    service = TTSService(tmp_path)
    (tmp_path / "reference_audio.wav").touch()

    def fail_generation(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'einops'", name="einops")

    monkeypatch.setattr(service, "_generate", fail_generation)
    with pytest.raises(HTTPException) as error:
        await _generate_audio(service, "你好", TTSConfig())

    assert error.value.status_code == 503
    assert "einops" in error.value.detail
    assert "bootstrap.py --voice" in error.value.detail
