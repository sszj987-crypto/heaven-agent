import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.services.container import ApplicationContainer, voice_dependencies_available


class Closable:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


async def test_llm_replacement_keeps_previous_client_alive_until_shutdown():
    container = object.__new__(ApplicationContainer)
    previous = Closable()
    replacement = Closable()
    updated = []
    container.llm = previous
    container.agent_loop = SimpleNamespace(update_llm_client=updated.append)
    container.distiller = SimpleNamespace(_llm=previous)
    container.jobs = SimpleNamespace(shutdown=_noop)
    container._retired_llms = []

    await container.replace_llm(replacement)

    assert container.llm is replacement
    assert updated == [replacement]
    assert container.distiller._llm is replacement
    assert previous.closed is False

    await container.close()
    assert replacement.closed is True
    assert previous.closed is True


async def test_voice_replacement_keeps_previous_service_alive_until_shutdown():
    container = object.__new__(ApplicationContainer)
    previous = Closable()
    replacement = Closable()
    updated = []
    tts_updates = []
    container.voice = previous
    container.status_service = SimpleNamespace(
        replace_voice=updated.append,
        update_tts=tts_updates.append,
    )
    container.settings = SimpleNamespace(tts=object())
    container.jobs = SimpleNamespace(shutdown=_noop)
    container.llm = Closable()
    container._retired_llms = []
    container._retired_voices = []

    await container.replace_voice(replacement)

    assert container.voice is replacement
    assert updated == [replacement]
    assert tts_updates == [container.settings.tts]
    assert previous.closed is False

    await container.close()
    assert replacement.closed is True
    assert previous.closed is True


async def test_save_cloud_voice_reference_retries_cleanup_before_creation():
    calls = []

    class CloudVoice:
        async def retry_cleanup(self):
            calls.append("cleanup")

        async def create_reference(self, audio, filename, content_type):
            calls.append((audio, filename, content_type))
            return b"RIFFpreview"

    container = object.__new__(ApplicationContainer)
    container.voice = CloudVoice()

    preview = await container.save_voice_reference(b"audio", "sample.wav", "audio/wav")

    assert preview == b"RIFFpreview"
    assert calls == ["cleanup", (b"audio", "sample.wav", "audio/wav")]


async def _noop():
    return None


def test_macos_voice_requires_all_runtime_modules(tmp_path):
    available, reason = voice_dependencies_available(
        "darwin",
        tmp_path,
        find_spec=lambda name: object() if name != "mlx_audio" else None,
    )

    assert available is False
    assert "mlx_audio" in reason


def test_macos_voice_requires_downloaded_model(tmp_path):
    available, reason = voice_dependencies_available(
        "darwin",
        tmp_path,
        find_spec=lambda _name: object(),
    )

    assert available is False
    assert "语音模型" in reason

    model = tmp_path / "deps" / "Fun-CosyVoice3-0.5B-2512-8bit" / "model.safetensors"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"weights")

    available, reason = voice_dependencies_available(
        "darwin",
        tmp_path,
        find_spec=lambda _name: object(),
    )
    assert available is True
    assert reason == ""


def test_cross_platform_voice_requires_cosyvoice_source(tmp_path):
    available, reason = voice_dependencies_available(
        "linux",
        tmp_path,
        find_spec=lambda _name: object(),
    )

    assert available is False
    assert "CosyVoice" in reason


async def test_demo_reset_waits_for_soul_mutation_lock():
    container = object.__new__(ApplicationContainer)
    container.soul_lock = asyncio.Lock()
    container.agent_loop = SimpleNamespace(
        _turn_lock=asyncio.Lock(),
        delete_history=lambda: None,
        invalidate_soul_cache=lambda: None,
    )
    container.data_management = SimpleNamespace(reset_demo=lambda *_args: Path("backup"))
    container.memory_store = None
    shutdowns = []
    container.jobs = SimpleNamespace(shutdown=lambda: _record(shutdowns))
    container.root = Path(".")
    await container.soul_lock.acquire()

    reset = asyncio.create_task(container.reset_demo())
    await asyncio.sleep(0)

    assert reset.done() is False
    container.soul_lock.release()
    assert await reset == Path("backup")
    assert shutdowns == [True]


async def _record(items):
    items.append(True)
