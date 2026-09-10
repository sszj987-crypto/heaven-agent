from types import SimpleNamespace
import asyncio
import io
import json
import tempfile
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from src.agent.context import PipelineContext
from src.api.chat_routes import _require_llm_settings, chat_audio
from src.api.schemas import (
    AudioRequest,
    MiniMaxSettingsUpdate,
    OnboardingStatus,
    SettingsUpdate,
    SystemCapabilities,
    SystemStatus,
    TTSSettingsUpdate,
)
from src.api.settings_routes import update_settings, upload_voice_sample
from src.config.loader import LLMConfig, MiniMaxConfig, VoiceProviderConfig
from src.main import create_app
from src.services.jobs import JobManager
from src.services.feedback import FeedbackStore
from src.services.voice_installation import (
    VoiceInstallationInProgress,
    VoiceInstallationStatus,
)
from src.voice.minimax import MiniMaxError


class FakeSettings:
    def __init__(self):
        self.llm = LLMConfig(
            base_url="https://api.test/v1",
            api_key="secret",
            model="test-model",
            temperature=0.5,
        )
        self.log_level = "error"
        self.tts = VoiceProviderConfig(
            provider="minimax",
            minimax=MiniMaxConfig(api_key="tts-secret"),
        )
        self.soul_id = "default"
        self.updated = None
        self.tts_updated = None

    def update_llm(self, **values):
        self.updated = values
        for key, value in values.items():
            setattr(self.llm, key, value)

    def update_log_level(self, level):
        self.log_level = level

    def update_tts(self, provider=None, minimax=None, openai_compatible=None, auto_play=None, audio_cache_size=None):
        self.tts_updated = {"provider": provider, "minimax": minimax, "openai_compatible": openai_compatible}
        if auto_play is not None:
            self.tts.auto_play = auto_play
        if audio_cache_size is not None:
            self.tts.audio_cache_size = audio_cache_size
        if provider is not None:
            self.tts.provider = provider
        for key, value in (minimax or {}).items():
            if value is not None:
                setattr(self.tts.minimax, key, value)
        for key, value in (openai_compatible or {}).items():
            if value is not None:
                setattr(self.tts.openai_compatible, key, value)


def test_local_ollama_chat_settings_do_not_require_a_user_api_key():
    config = LLMConfig(provider="local")
    config.ollama.model = "qwen3:8b"
    container = SimpleNamespace(settings=SimpleNamespace(llm=config))

    _require_llm_settings(container)


class FakeAgent:
    messages = []

    async def run_once(self, message):
        ctx = PipelineContext(user_message=message)
        ctx.response = "测试回复"
        ctx.instruct_text = "温柔地说"
        ctx.retrieved_memories = [{
            "id": "mem_1",
            "document": "喜欢桂花糕",
            "metadata": {"dimension": "personal_traits", "source_type": "import"},
        }]
        return ctx

    async def stream_once(self, message):
        yield {"type": "done", "context": await self.run_once(message)}


class EmptyVoice:
    has_reference = True

    async def speak(self, _text, _config):
        yield b""


class FailingVoice:
    has_reference = True

    async def speak(self, _text, _config):
        if False:
            yield b""
        raise RuntimeError("PRIVATE_TTS_DETAIL")


class FakeCloudVoice:
    supports_instruction = True

    def __init__(
        self,
        *,
        has_reference=False,
        preview=None,
        creating=False,
        last_error="",
        speak_error=None,
    ):
        self.has_reference = has_reference
        self.activation_preview = preview
        self.creating = creating
        self.last_error = last_error
        self.speak_error = speak_error

    async def create_reference(self, audio, filename, content_type):
        self.has_reference = True
        self.last_reference = (audio, filename, content_type)
        return self.activation_preview

    async def retry_cleanup(self):
        self.cleanup_retried = True

    async def speak(self, _text, _config):
        if self.speak_error is not None:
            raise self.speak_error
        yield b"RIFFcloud-audio"

    async def aclose(self):
        self.closed = True


class FakeContainer:
    def __init__(self):
        self.settings = FakeSettings()
        self.layout = SimpleNamespace(data_root=Path("/data"), voice_dir=Path("/data/voice"))
        self.soul_loader = SimpleNamespace(load=lambda: SimpleNamespace(name="王奶奶"))
        self.feedback = FeedbackStore(Path(tempfile.mkdtemp()) / "feedback.json")
        self.root = Path("/project")
        self.soul_lock = asyncio.Lock()
        self.agent_loop = FakeAgent()
        self.voice = FakeCloudVoice()
        self.replaced = False
        self.voice_replaced = False
        self.saved_voice_filename = None
        self.closed = False
        self.demo_reset = False
        self.jobs = JobManager()
        self.distiller = SimpleNamespace(distill=self._distill)
        self.import_reviews = SimpleNamespace(queue=self._queue_import)
        self.queued_import = None
        self.data_management = SimpleNamespace(
            diagnostics=lambda **_kwargs: {
                "soul_id": "default",
                "python": "3.13.0",
                "platform": "test",
                "supported_python": True,
                "profile_files": 6,
                "voice_installed": False,
                "voice_ready": False,
                "memory_ready": False,
                "ffmpeg": False,
            },
            export_zip=lambda: b"PK\x03\x04test-export",
        )
        self.voice_installed = False
        self.voice_installation = SimpleNamespace(
            status=lambda: VoiceInstallationStatus(
                state="not_installed",
                stage="idle",
                message="语音组件未安装",
            ),
            start=lambda: SimpleNamespace(id="job_voice_install"),
        )
        self.memory_store = None
        self.onboarding_steps = []
        self.onboarding = SimpleNamespace(mark_step=self.onboarding_steps.append)
        self.status_service = SimpleNamespace(get=lambda: SystemStatus(
            initialization="ready",
            soul_id="default",
            soul_name="王奶奶",
            capabilities=SystemCapabilities(),
            onboarding=OnboardingStatus(
                profile_ready=True,
                import_review_ready=True,
                voice_ready=False,
                completed=True,
            ),
            pending_jobs=0,
            pending_candidates=0,
        ))

    async def replace_llm(self, replacement=None):
        self.replaced = True
        self.replacement = replacement

    async def replace_voice(self, replacement=None):
        self.voice_replaced = True
        if replacement is not None:
            self.voice = replacement

    async def save_voice_reference(self, audio, filename, content_type):
        self.saved_voice_filename = filename
        retry_cleanup = getattr(self.voice, "retry_cleanup", None)
        if retry_cleanup is not None:
            await retry_cleanup()
        create_reference = getattr(self.voice, "create_reference", None)
        if create_reference is not None:
            return await create_reference(audio, filename, content_type)
        return None

    async def reset_demo(self):
        self.demo_reset = True
        return Path("/data/backups/reset-test/default")

    async def _distill(self, raw_text, chat_name="", *, apply_changes=True):
        assert apply_changes is False
        return SimpleNamespace(
            changes=["personality"],
            profile={"personality": "- 乐观"},
            summary="发现性格特征",
            skill_card=None,
        )

    def _queue_import(self, result, raw_text, **kwargs):
        self.queued_import = (result, raw_text, kwargs)
        return [SimpleNamespace(id="candidate_1")]

    async def close(self):
        self.closed = True


def make_client():
    container = FakeContainer()
    app = create_app(lambda _root, _settings: container)
    return TestClient(app), container


def test_auto_play_setting_can_be_toggled_without_replacing_voice():
    client, container = make_client()
    with client:
        assert client.get("/settings").json()["tts"]["auto_play"] is False
        for enabled in (True, False):
            response = client.put("/settings", json={"tts": {"auto_play": enabled}})
            assert response.status_code == 200
            assert client.get("/settings").json()["tts"]["auto_play"] is enabled
            assert container.voice_replaced is False


@pytest.mark.parametrize("provider", ["local", "minimax"])
def test_saving_auto_play_from_full_settings_form_keeps_loaded_voice(provider):
    client, container = make_client()
    container.settings.tts.provider = provider
    active_voice = container.voice
    with client:
        for enabled in (True, False):
            response = client.put("/settings", json={"tts": {
                "provider": provider,
                "auto_play": enabled,
                "minimax": {"base_url": "https://api.minimaxi.com", "model": "speech-2.8-hd"},
            }})
            assert response.status_code == 200
            assert container.voice is active_voice
            assert client.get("/settings").json()["tts"]["auto_play"] is enabled


def test_chat_response_includes_memory_provenance():
    client, _ = make_client()
    with client:
        response = client.post("/chat", json={"message": "还记得吗"})

    assert response.status_code == 200
    assert response.json()["used_memories"] == [{
        "id": "mem_1",
        "content": "喜欢桂花糕",
        "dimension": "personal_traits",
        "source_type": "import",
    }]
    assert response.json()["response_id"].startswith("reply_")
    assert response.json()["timing"]["first_response_ms"] is None
    assert isinstance(response.json()["timing"]["total_response_ms"], int)
    assert response.json()["timing"]["total_response_ms"] >= 0


def test_chat_stream_response_includes_response_id():
    client, _ = make_client()
    with client:
        response = client.post("/chat/stream", json={"message": "还记得吗"})

    assert response.status_code == 200
    assert '"response_id": "reply_' in response.text
    assert '"timing": {' in response.text
    assert '"first_response_ms": null' in response.text


def test_chat_stream_reports_first_response_timing():
    class StreamingAgent(FakeAgent):
        async def stream_once(self, message):
            yield {"type": "delta", "content": "测试"}
            yield {"type": "done", "context": await self.run_once(message)}

    client, container = make_client()
    container.agent_loop = StreamingAgent()
    with client:
        response = client.post("/chat/stream", json={"message": "还记得吗"})

    packets = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    done = next(packet for packet in packets if packet["type"] == "done")
    assert done["timing"]["first_response_ms"] is not None
    assert done["timing"]["first_response_ms"] >= 0
    assert done["timing"]["total_response_ms"] >= done["timing"]["first_response_ms"]


def test_voice_chat_response_includes_response_id(monkeypatch):
    client, container = make_client()
    container.voice_installed = True

    class SuccessfulASR:
        async def transcribe(self, _audio):
            return "语音转写"

    monkeypatch.setattr("src.api.chat_routes.create_asr_service", lambda: SuccessfulASR())
    with client:
        response = client.post(
            "/chat/voice",
            files={"audio": ("voice.wav", b"RIFFdata", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["response_id"].startswith("reply_")


def test_chat_feedback_is_upserted_and_counted():
    client, _ = make_client()
    payload = {
        "user_message": "你今天好吗？",
        "response_text": "我很好呀。",
        "rating": "dissimilar",
        "reasons": ["style", "relationship"],
        "suggestion": "她会先叫我的小名。",
    }
    with client:
        first = client.put("/chat/feedback/reply_test", json=payload)
        replacement = client.put("/chat/feedback/reply_test", json={
            **payload,
            "rating": "similar",
            "reasons": [],
            "suggestion": "",
        })
        stats = client.get("/chat/feedback/stats")

    assert first.status_code == 200
    assert replacement.status_code == 200
    assert stats.json() == {
        "total": 1,
        "similar": 1,
        "dissimilar": 0,
        "similar_rate": 1.0,
        "reasons": {"fact": 0, "other": 0, "relationship": 0, "response": 0, "style": 0},
    }


def test_import_preview_requires_an_explicit_existing_speaker():
    client, container = make_client()
    chat = "王奶奶: 今天做桂花糕\n小明: 我想吃"
    with client:
        preview = client.post("/soul/import-preview", files={"file": ("chat.txt", chat, "text/plain")})
        missing = client.post("/soul/imports", files={"file": ("chat.txt", chat, "text/plain")})
        invalid = client.post(
            "/soul/imports",
            files={"file": ("chat.txt", chat, "text/plain")},
            data={"chat_name": "不存在"},
        )

    assert preview.status_code == 200
    assert preview.json()["speakers"] == [
        {"name": "小明", "message_count": 1, "matches_profile_name": False},
        {"name": "王奶奶", "message_count": 1, "matches_profile_name": True},
    ]
    assert missing.status_code == 422
    assert invalid.status_code == 422
    assert container.queued_import is None


def test_chat_audio_rejects_empty_voice_output():
    client, container = make_client()
    container.voice = EmptyVoice()
    with client:
        response = client.post(
            "/chat/audio",
            json={"text": "你好", "instruct_text": "平静地说"},
        )

    assert response.status_code == 500
    assert response.json()["message"] == "语音准备失败，请重试"


def test_chat_audio_rejects_tts_exception_without_private_detail():
    client, container = make_client()
    container.voice = FailingVoice()
    with client:
        response = client.post(
            "/chat/audio",
            json={"text": "你好", "instruct_text": "平静地说"},
        )

    assert response.status_code == 500
    assert response.json()["message"] == "语音准备失败，请重试"
    assert "PRIVATE_TTS_DETAIL" not in response.text


def test_chat_audio_returns_safe_non_retryable_minimax_credentials_error():
    client, container = make_client()
    container.voice = FakeCloudVoice(
        has_reference=True,
        speak_error=MiniMaxError("MiniMax API Key 无效或无权限"),
    )
    with client:
        response = client.post("/chat/audio", json={"text": "你好"})

    assert response.status_code == 502
    assert response.json()["code"] == "minimax_error"
    assert response.json()["message"] == "MiniMax API Key 无效或无权限"
    assert response.json()["retryable"] is False


def test_chat_audio_returns_retryable_minimax_quota_error_without_fallback():
    client, container = make_client()
    container.voice = FakeCloudVoice(
        has_reference=True,
        speak_error=MiniMaxError("MiniMax 请求频率或额度受限", retryable=True),
    )
    with client:
        response = client.post("/chat/audio", json={"text": "你好"})

    assert response.status_code == 502
    assert response.json()["code"] == "minimax_error"
    assert response.json()["message"] == "MiniMax 请求频率或额度受限"
    assert response.json()["retryable"] is True


def test_settings_view_never_returns_masked_or_real_api_key():
    client, _ = make_client()
    with client:
        response = client.get("/settings")

    assert response.status_code == 200
    assert response.json()["llm"]["cloud"]["api_key_configured"] is True
    assert "api_key" not in response.json()["llm"]


def test_settings_view_masks_minimax_key():
    client, _ = make_client()
    with client:
        payload = client.get("/settings").json()

    assert payload["tts"] == {
        "provider": "minimax",
        "auto_play": False,
        "audio_cache_size": 10,
        "minimax": {
            "base_url": "https://api.minimaxi.com",
            "model": "speech-2.8-hd",
            "api_key_configured": True,
        },
        "openai_compatible": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini-tts",
            "voice": "alloy",
            "api_key_configured": False,
        },
    }


def test_openai_compatible_tts_update_hot_replaces_without_exposing_key():
    client, container = make_client()
    with client:
        response = client.put(
            "/settings",
            json={"tts": {
                "provider": "openai_compatible",
                "openai_compatible": {
                    "base_url": "https://newapi.example/v1",
                    "api_key": "new-key",
                    "model": "custom-tts",
                    "voice": "voice_123",
                },
            }},
        )

    assert response.status_code == 200
    assert container.settings.tts.provider == "openai_compatible"
    assert container.settings.tts.openai_compatible.api_key == "new-key"
    assert container.settings.tts.openai_compatible.voice == "voice_123"
    assert container.voice_replaced is True


def test_openai_compatible_voice_is_ready_without_reference_and_rejects_upload():
    client, container = make_client()
    container.settings.tts.provider = "openai_compatible"
    container.settings.tts.openai_compatible.api_key = "configured"
    container.voice = SimpleNamespace(
        has_reference=False,
        is_ready=True,
        supports_instruction=True,
    )
    with client:
        status = client.get("/settings/voice/status")
        upload = client.post(
            "/settings/voice/upload",
            files={"audio": ("sample.wav", b"RIFFsample", "audio/wav")},
        )

    assert status.status_code == 200
    assert status.json()["ready"] is True
    assert status.json()["has_reference"] is False
    assert status.json()["supports_voice_cloning"] is False
    assert upload.status_code == 400


def test_tts_update_hot_replaces_voice_without_exposing_key():
    client, container = make_client()
    with client:
        response = client.put(
            "/settings",
            json={"tts": {"provider": "minimax", "minimax": {"api_key": "new-key"}}},
        )

    assert response.status_code == 200
    assert container.settings.tts.minimax.api_key == "new-key"
    assert container.voice_replaced is True


def test_invalid_tts_replacement_does_not_persist_settings(monkeypatch):
    client, container = make_client()
    original_model = container.settings.tts.minimax.model

    def reject(_settings, _data_dir, _root, _soul_id):
        raise ValueError("invalid MiniMax endpoint")

    monkeypatch.setattr("src.api.settings_routes._create_selected_voice", reject)
    with client:
        response = client.put(
            "/settings",
            json={"tts": {"minimax": {"model": "broken-model"}}},
        )

    assert response.status_code == 400
    assert container.settings.tts.minimax.model == original_model
    assert container.voice_replaced is False


async def test_queued_tts_updates_build_from_configuration_after_lock(monkeypatch):
    container = FakeContainer()
    constructed = []

    class BuiltVoice:
        def __init__(self, config):
            self.api_key = config.api_key
            self.model = config.model

    def build(settings, _data_dir, _root, _soul_id):
        voice = BuiltVoice(settings.tts.minimax)
        constructed.append(voice)
        return voice

    monkeypatch.setattr("src.api.settings_routes._create_selected_voice", build)
    await container.soul_lock.acquire()
    first = asyncio.create_task(update_settings(
        SettingsUpdate(tts=TTSSettingsUpdate(
            minimax=MiniMaxSettingsUpdate(api_key="new-key"),
        )),
        container,
    ))
    await asyncio.sleep(0)
    second = asyncio.create_task(update_settings(
        SettingsUpdate(tts=TTSSettingsUpdate(
            minimax=MiniMaxSettingsUpdate(model="new-model"),
        )),
        container,
    ))
    await asyncio.sleep(0)
    container.soul_lock.release()
    await asyncio.gather(first, second)

    assert container.settings.tts.minimax.api_key == "new-key"
    assert container.settings.tts.minimax.model == "new-model"
    assert container.voice.api_key == "new-key"
    assert container.voice.model == "new-model"
    assert [(voice.api_key, voice.model) for voice in constructed] == [
        ("new-key", "speech-2.8-hd"),
        ("new-key", "new-model"),
    ]


async def test_tts_persistence_failure_closes_unadopted_replacement_and_keeps_active_voice(
    monkeypatch
):
    container = FakeContainer()
    previous = container.voice
    replacement = FakeCloudVoice()

    def fail_update_tts(**_kwargs):
        raise OSError("settings write failed")

    container.settings.update_tts = fail_update_tts
    monkeypatch.setattr(
        "src.api.settings_routes._create_selected_voice", lambda *_args: replacement
    )

    with pytest.raises(OSError, match="settings write failed"):
        await update_settings(
            SettingsUpdate(tts=TTSSettingsUpdate(minimax=MiniMaxSettingsUpdate(model="new-model"))),
            container,
        )

    assert replacement.closed is True
    assert container.voice is previous


async def test_cloud_chat_audio_blocks_voice_replacement_until_synthesis_finishes():
    container = FakeContainer()
    synthesis_started = asyncio.Event()
    release_synthesis = asyncio.Event()
    events = []

    class BlockingVoice(FakeCloudVoice):
        async def speak(self, _text, _config):
            events.append("synthesis_started")
            synthesis_started.set()
            await release_synthesis.wait()
            events.append("synthesis_finished")
            yield b"RIFFcloud-audio"

        async def create_reference(self, _audio, _filename, _content_type):
            events.append("old_voice_deleted")
            return b"RIFFpreview"

    container.voice = BlockingVoice(has_reference=True)
    audio_task = asyncio.create_task(chat_audio(AudioRequest(text="你好"), container))
    await synthesis_started.wait()
    upload_task = asyncio.create_task(
        upload_voice_sample(UploadFile(filename="sample.wav", file=io.BytesIO(b"RIFFsample")), container)
    )
    await asyncio.sleep(0)

    assert events == ["synthesis_started"]
    release_synthesis.set()
    await asyncio.wait_for(audio_task, timeout=1)
    await asyncio.wait_for(upload_task, timeout=1)
    assert events == ["synthesis_started", "synthesis_finished", "old_voice_deleted"]


async def test_cloud_chat_audio_selects_hot_replacement_after_acquiring_soul_lock(
    monkeypatch
):
    container = FakeContainer()
    calls = []

    class NamedVoice(FakeCloudVoice):
        def __init__(self, name):
            super().__init__(has_reference=True)
            self.name = name

        async def speak(self, _text, _config):
            calls.append(self.name)
            yield self.name.encode()

    old_voice = NamedVoice("old")
    new_voice = NamedVoice("new")
    container.voice = old_voice
    monkeypatch.setattr("src.api.settings_routes._create_selected_voice", lambda *_args: new_voice)
    await container.soul_lock.acquire()
    update_task = asyncio.create_task(
        update_settings(
            SettingsUpdate(tts=TTSSettingsUpdate(minimax=MiniMaxSettingsUpdate(model="new-model"))),
            container,
        )
    )
    await asyncio.sleep(0)
    audio_task = asyncio.create_task(chat_audio(AudioRequest(text="你好"), container))
    await asyncio.sleep(0)
    container.soul_lock.release()

    await asyncio.wait_for(update_task, timeout=1)
    response = await asyncio.wait_for(audio_task, timeout=1)
    assert response.body == b"new"
    assert calls == ["new"]


def test_tts_update_accepts_null_minimax_as_no_change():
    container = FakeContainer()
    app = create_app(lambda _root, _settings: container)
    client = TestClient(app, raise_server_exceptions=False)
    with client:
        response = client.put("/settings", json={"tts": {"minimax": None}})

    assert response.status_code == 200
    assert container.settings.tts.minimax.api_key == "tts-secret"
    assert container.voice_replaced is False


def test_tts_null_update_does_not_skip_log_level_update():
    client, container = make_client()
    with client:
        response = client.put(
            "/settings",
            json={"tts": {"minimax": None}, "log_level": "debug"},
        )

    assert response.status_code == 200
    assert container.settings.log_level == "debug"


def test_settings_update_omits_api_key_and_replaces_live_client():
    client, container = make_client()
    with client:
        response = client.put("/settings", json={"llm": {"model": "new-model"}})

    assert response.status_code == 200
    assert container.settings.updated == {"model": "new-model"}
    assert container.settings.llm.api_key == "secret"
    assert container.replaced is True


def test_invalid_llm_update_does_not_persist_or_replace(monkeypatch):
    client, container = make_client()
    original_url = container.settings.llm.base_url

    def reject_invalid(config):
        if config.base_url == "":
            raise ValueError("missing base url")
        return object()

    monkeypatch.setattr("src.api.settings_routes.LLMManager.get_client", reject_invalid)
    with client:
        response = client.put("/settings", json={"llm": {"base_url": ""}})

    assert response.status_code == 400
    assert container.settings.llm.base_url == original_url
    assert container.settings.updated is None
    assert container.replaced is False


def test_system_status_exposes_onboarding_and_capabilities():
    client, container = make_client()
    with client:
        response = client.get("/system/status")

    assert response.status_code == 200
    assert response.json()["onboarding"]["completed"] is True
    assert response.json()["capabilities"]["text_chat"] is True
    assert container.closed is True


def test_voice_status_exposes_instruction_capability_without_overpromising():
    client, container = make_client()
    container.settings.tts.minimax.api_key = ""
    with client:
        response = client.get("/settings/voice/status")

    assert response.status_code == 200
    assert response.json() == {
        "has_reference": False,
        "ready": False,
        "supports_instruction": True,
        "supports_voice_cloning": True,
        "preview_available": False,
        "provider": "minimax",
        "state": "not_configured",
        "message": "请先在设置中配置 MiniMax API Key",
    }


def test_cloud_voice_status_does_not_require_local_installation():
    client, container = make_client()
    container.voice = FakeCloudVoice(has_reference=True, preview=b"RIFFpreview")
    container.voice_installed = False
    with client:
        payload = client.get("/settings/voice/status").json()

    assert payload["provider"] == "minimax"
    assert payload["state"] == "ready"
    assert payload["has_reference"] is True
    assert payload["preview_available"] is True


def test_cloud_voice_status_reports_no_voice_and_safe_failed_state():
    client, container = make_client()
    container.settings.tts.minimax.api_key = "configured"
    with client:
        no_voice = client.get("/settings/voice/status").json()
    container.voice = FakeCloudVoice(last_error="MiniMax 云端音色创建失败")
    with client:
        failed = client.get("/settings/voice/status").json()

    assert no_voice["state"] == "no_voice"
    assert failed["state"] == "failed"
    assert failed["message"] == "MiniMax 云端音色创建失败"


@pytest.mark.parametrize(
    ("provider", "preview", "creating"),
    [("local", b"saved-preview", False), ("minimax", None, False),
     ("minimax", b"saved-preview", True)],
)
def test_status_only_offers_saved_preview_for_ready_cloud_voice(provider, preview, creating):
    client, container = make_client()
    container.settings.tts.provider = provider
    container.voice_installed = True
    container.voice = FakeCloudVoice(has_reference=True, preview=preview, creating=creating)
    with client:
        response = client.get("/settings/voice/status")

    assert response.status_code == 200
    assert response.json()["preview_available"] is False


def test_voice_upload_uses_async_provider_operation_when_local_voice_is_unavailable():
    client, container = make_client()
    container.settings.tts.minimax.api_key = "configured"
    preview = b"RIFFpreview"
    container.voice = FakeCloudVoice(preview=preview)
    with client:
        response = client.post(
            "/settings/voice/upload",
            files={"audio": ("sample.wav", b"RIFFsample", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "preview_available": True}
    assert container.saved_voice_filename == "sample.wav"
    assert container.voice.last_reference == (b"RIFFsample", "sample.wav", "audio/wav")
    assert container.voice.cleanup_retried is True


def test_tts_connection_uses_cloud_service_without_generating_audio(monkeypatch):
    client, container = make_client()
    called = []

    class ConnectionClient:
        def __init__(self, base_url, api_key):
            called.append((base_url, api_key))

        async def test_connection(self):
            return True

        async def aclose(self):
            called.append("closed")

    monkeypatch.setattr("src.api.settings_routes.MiniMaxClient", ConnectionClient)
    with client:
        response = client.post("/settings/test-tts")

    assert response.json() == {"connected": True}
    assert called == [("https://api.minimaxi.com", "tts-secret"), "closed"]


def test_cloud_activation_preview_is_available_only_for_ready_cloud_voice():
    client, container = make_client()
    container.settings.tts.minimax.api_key = "configured"
    container.voice = FakeCloudVoice(has_reference=True, preview=b"RIFFpreview")
    with client:
        preview = client.get("/settings/voice/preview")

    assert preview.status_code == 200
    assert preview.headers["content-type"] == "audio/wav"
    assert preview.content == b"RIFFpreview"


def test_voice_preview_is_not_available_for_local_or_missing_cloud_preview():
    client, container = make_client()
    container.settings.tts.provider = "local"
    with client:
        local = client.get("/settings/voice/preview")
    container.settings.tts.provider = "minimax"
    with client:
        missing = client.get("/settings/voice/preview")

    assert local.status_code == 404
    assert missing.status_code == 404


def test_voice_installation_status_exposes_only_current_state():
    client, _ = make_client()
    with client:
        response = client.get("/system/voice-installation")

    assert response.status_code == 200
    assert response.json() == {
        "state": "not_installed",
        "stage": "idle",
        "message": "语音组件未安装",
        "restart_required": False,
        "job_id": None,
    }


def test_voice_installation_requires_confirmation_header_and_returns_job():
    client, _ = make_client()
    with client:
        rejected = client.post("/system/voice-installation")
        accepted = client.post(
            "/system/voice-installation",
            headers={"X-Heaven-Action": "install-voice"},
        )

    assert rejected.status_code == 403
    assert accepted.status_code == 202
    assert accepted.json() == {"job_id": "job_voice_install"}


def test_voice_installation_rejects_a_duplicate_active_task():
    client, container = make_client()

    def reject_duplicate():
        raise VoiceInstallationInProgress

    container.voice_installation.start = reject_duplicate
    with client:
        response = client.post(
            "/system/voice-installation",
            headers={"X-Heaven-Action": "install-voice"},
        )

    assert response.status_code == 409


def test_voice_installation_openapi_responses_are_typed():
    client, _ = make_client()
    with client:
        paths = client.get("/openapi.json").json()["paths"]

    endpoint = paths["/system/voice-installation"]
    assert endpoint["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("VoiceInstallationView")
    assert endpoint["post"]["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith("JobAccepted")


def test_onboarding_step_requires_explicit_supported_marker():
    client, container = make_client()
    with client:
        response = client.post("/system/onboarding/steps/profile")
        invalid = client.post("/system/onboarding/steps/unknown")

    assert response.status_code == 200
    assert container.onboarding_steps == ["profile"]
    assert invalid.status_code == 422


def test_validation_errors_use_unified_error_contract():
    client, _ = make_client()
    with client:
        response = client.post("/chat", json={"message": ""})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["retryable"] is False
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_unhandled_errors_use_unified_error_contract():
    container = FakeContainer()
    app = create_app(lambda _root, _settings: container)

    @app.get("/test-unhandled-error")
    async def _boom():
        raise RuntimeError("private internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    with client:
        response = client.get("/test-unhandled-error")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["message"] == "服务器内部错误"
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_asr_failure_does_not_expose_internal_error(monkeypatch):
    container = FakeContainer()
    container.voice_installed = True

    class FailingASR:
        async def transcribe(self, _audio):
            raise RuntimeError("PRIVATE_AUDIO_PATH")

    monkeypatch.setattr("src.api.chat_routes.create_asr_service", lambda: FailingASR())
    app = create_app(lambda _root, _settings: container)
    with TestClient(app) as client:
        response = client.post(
            "/chat/voice",
            files={"audio": ("voice.wav", b"RIFFdata", "audio/wav")},
        )

    assert response.status_code == 500
    assert response.json()["message"] == "语音识别失败，请稍后重试"
    assert "PRIVATE_AUDIO_PATH" not in response.text


def test_soul_import_returns_job_and_queues_preview_candidates():
    client, container = make_client()
    with client:
        accepted = client.post(
            "/soul/imports",
            files={"file": ("chat.txt", "用户: 你很乐观", "text/plain")},
            data={"chat_name": "用户"},
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        for _ in range(20):
            response = client.get(f"/jobs/{job_id}")
            if response.json()["status"] == "completed":
                break
            asyncio.run(asyncio.sleep(0.01))

    assert response.json()["result"]["candidate_count"] == 1
    assert container.queued_import is not None
    assert container.queued_import[2]["source_speaker"] == "用户"


def test_system_diagnostics_is_typed_and_secret_free():
    client, _ = make_client()
    with client:
        response = client.get("/system/diagnostics")

    assert response.status_code == 200
    assert response.json()["supported_python"] is True
    assert "api_key" not in response.text


def test_system_export_downloads_current_soul_archive():
    client, _ = make_client()
    with client:
        response = client.get("/system/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "heaven-default" in response.headers["content-disposition"]


def test_demo_reset_is_explicit_and_returns_recoverable_backup():
    client, container = make_client()
    with client:
        rejected = client.post("/system/demo-reset")
        response = client.post(
            "/system/demo-reset",
            headers={"x-heaven-action": "demo-reset"},
        )

    assert rejected.status_code == 403
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "recoverable": True,
        "backup": "backups/reset-test/default",
    }
    assert container.demo_reset is True


def test_json_capability_routes_have_nonempty_openapi_schemas():
    client, _ = make_client()
    with client:
        paths = client.get("/openapi.json").json()["paths"]

    operations = (
        ("/soul/circumstances", "get"),
        ("/soul/circumstances", "put"),
        ("/soul/skill", "get"),
        ("/soul/distill", "post"),
        ("/memory/{dimension}", "get"),
        ("/memory/{memory_id}", "delete"),
    )
    for path, method in operations:
        schema = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema, f"missing response schema for {method.upper()} {path}"
