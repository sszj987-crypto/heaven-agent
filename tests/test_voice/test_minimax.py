import asyncio
import json
import hashlib
import io
import re
import wave

import httpx
import pytest

from src.agent.context import TTSConfig
from src.config.loader import MiniMaxConfig
from src.voice.cloud_store import CloudVoiceProfile, CloudVoiceStore
from src.voice.minimax import (
    ACTIVATION_TEXT,
    MiniMaxClient,
    MiniMaxError,
    MiniMaxTTSService,
    instruction_to_emotion,
)
from src.voice.service import DisabledVoiceService, VoiceUnavailable


def make_client(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MiniMaxClient("https://example.minimax.test/", "test-key", client=http)


def valid_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00")
    return buffer.getvalue()


def minimax_config() -> MiniMaxConfig:
    return MiniMaxConfig(api_key="test-key", model="speech-2.8-hd")


def old_profile() -> CloudVoiceProfile:
    return CloudVoiceProfile(
        provider="minimax",
        voice_id="oldvoice1234",
        model="speech-2.8-hd",
        created_at="2026-09-03T00:00:00+00:00",
        source_sha256=hashlib.sha256(b"old").hexdigest(),
    )


class RecordingMiniMaxClient:
    def __init__(
        self,
        *,
        activation_audio: bytes | None = None,
        activation_error: Exception | None = None,
        failed_file_ids: set[int] | None = None,
        failed_voice_ids: set[str] | None = None,
    ):
        self.activation_audio = activation_audio or valid_wav()
        self.activation_error = activation_error
        self.failed_file_ids = failed_file_ids or set()
        self.failed_voice_ids = failed_voice_ids or set()
        self.created_voice_id = "createdvoice1234"
        self.calls: list[str] = []
        self.synthesis_requests: list[tuple[str, str, str, str]] = []
        self.closed = False

    async def upload_clone_audio(self, _audio, _filename, _content_type):
        self.calls.append("upload")
        return 1234

    async def clone_voice(self, _file_id, voice_id, _model):
        self.calls.append("clone")
        self.created_voice_id = voice_id

    async def synthesize(self, text, voice_id, model, instruct_text):
        self.synthesis_requests.append((text, voice_id, model, instruct_text))
        if text == ACTIVATION_TEXT:
            self.calls.append("activate")
            if self.activation_error is not None:
                raise self.activation_error
            return self.activation_audio
        self.calls.append("speak")
        return valid_wav()

    async def delete_file(self, file_id):
        self.calls.append("delete_file")
        if file_id in self.failed_file_ids:
            raise MiniMaxError("MiniMax 语音服务调用失败")

    async def delete_voice(self, voice_id):
        self.calls.append(
            "delete_old_voice" if voice_id == "oldvoice1234" else "delete_candidate_voice"
        )
        if voice_id in self.failed_voice_ids:
            raise MiniMaxError("MiniMax 语音服务调用失败")

    async def aclose(self):
        self.closed = True


async def test_create_reference_activates_before_replacing_old_voice(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    client = RecordingMiniMaxClient(activation_audio=valid_wav())
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    preview = await service.create_reference(
        b"new-source", "recording.wav", "audio/wav"
    )

    assert preview == valid_wav()
    assert service.activation_preview == valid_wav()
    assert store.load().voice_id == client.created_voice_id
    assert client.calls == [
        "upload",
        "clone",
        "activate",
        "delete_file",
        "delete_old_voice",
    ]


async def test_create_reference_preserves_active_profile_when_activation_fails(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    client = RecordingMiniMaxClient(
        activation_error=MiniMaxError("MiniMax 返回的语音无效", retryable=True)
    )
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    with pytest.raises(MiniMaxError, match="MiniMax 返回的语音无效"):
        await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert store.load().voice_id == old_profile().voice_id
    assert "delete_candidate_voice" in client.calls


async def test_create_reference_rejects_invalid_activation_audio_before_replacing_voice(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    client = RecordingMiniMaxClient(activation_audio=b"not-a-wav")
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    with pytest.raises(MiniMaxError, match="MiniMax 返回的语音无效"):
        await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert store.load().voice_id == old_profile().voice_id
    assert "delete_candidate_voice" in client.calls


async def test_create_reference_rejects_zero_frame_wav_before_replacing_voice(tmp_path):
    empty_wav = io.BytesIO()
    with wave.open(empty_wav, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    client = RecordingMiniMaxClient(activation_audio=empty_wav.getvalue())
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    with pytest.raises(MiniMaxError, match="MiniMax 返回的语音无效"):
        await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert store.load().voice_id == old_profile().voice_id
    assert client.calls[-2:] == ["delete_candidate_voice", "delete_file"]


async def test_failed_replacement_exposes_safe_error_without_losing_active_voice(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    service = MiniMaxTTSService(
        tmp_path,
        "default",
        minimax_config(),
        client=RecordingMiniMaxClient(
            activation_error=MiniMaxError("MiniMax 返回的语音无效", retryable=True)
        ),
    )

    assert service.creating is False
    with pytest.raises(MiniMaxError):
        await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert service.creating is False
    assert service.has_reference is True
    assert service.last_error == "MiniMax 云端音色创建失败"
    assert store.load().last_error == "MiniMax 云端音色创建失败"


async def test_failed_publication_cleans_candidate_and_file_when_error_status_write_fails(
    tmp_path, monkeypatch
):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old-source", valid_wav())
    client = RecordingMiniMaxClient()
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    def fail_write(_profile):
        raise OSError("metadata unavailable")

    monkeypatch.setattr(service._store, "_write_profile", fail_write)

    with pytest.raises(OSError, match="metadata unavailable"):
        await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert client.calls[-2:] == ["delete_candidate_voice", "delete_file"]
    assert store.load().voice_id == old_profile().voice_id


async def test_create_reference_cancellation_runs_bounded_cleanup_then_propagates(tmp_path):
    activation_started = asyncio.Event()

    class CancelledActivationClient(RecordingMiniMaxClient):
        async def synthesize(self, text, voice_id, model, instruct_text):
            if text == ACTIVATION_TEXT:
                self.calls.append("activate")
                activation_started.set()
                await asyncio.Future()
            return await super().synthesize(text, voice_id, model, instruct_text)

    client = CancelledActivationClient()
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)
    task = asyncio.create_task(
        service.create_reference(b"new-source", "recording.wav", "audio/wav")
    )
    await activation_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    assert client.calls[-2:] == ["delete_candidate_voice", "delete_file"]
    assert service.creating is False


async def test_create_reference_records_failed_temporary_file_cleanup(tmp_path):
    client = RecordingMiniMaxClient(failed_file_ids={1234})
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert CloudVoiceStore(tmp_path).load().pending_cleanup == [
        {"kind": "file", "remote_id": "1234"}
    ]


async def test_cleanup_and_status_persistence_failures_preserve_original_error(tmp_path, monkeypatch):
    original = MiniMaxError("original activation failure")
    client = RecordingMiniMaxClient(
        activation_error=original, failed_file_ids={1234}, failed_voice_ids={"candidate1234"},
    )
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)
    monkeypatch.setattr(service, "_make_voice_id", lambda: "candidate1234")

    def fail_persistence(*_args):
        raise OSError("cleanup/status persistence failure")

    monkeypatch.setattr(service._store, "set_last_error", fail_persistence)
    monkeypatch.setattr(service._store, "add_pending_cleanup", fail_persistence)
    with pytest.raises(MiniMaxError) as error:
        await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert error.value is original
    assert client.calls[-2:] == ["delete_candidate_voice", "delete_file"]
    assert service.creating is False


async def test_cancelled_activation_bounds_each_cleanup_and_leaves_no_running_deletes(tmp_path):
    started = asyncio.Event()
    active_deletes = set()
    finished_deletes = []

    class HangingCleanupClient(RecordingMiniMaxClient):
        async def synthesize(self, *_args):
            started.set()
            await asyncio.Future()

        async def delete_voice(self, _voice_id):
            await self.hang("voice")

        async def delete_file(self, _file_id):
            await self.hang("file")

        async def hang(self, kind):
            active_deletes.add(kind)
            try:
                await asyncio.Future()
            finally:
                active_deletes.remove(kind)
                finished_deletes.append(kind)

    client = HangingCleanupClient()
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)
    service._CLEANUP_TIMEOUT_SECONDS = 0.01
    task = asyncio.create_task(service.create_reference(b"source", "sample.wav", "audio/wav"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    assert active_deletes == set()
    assert finished_deletes == ["voice", "file"]
    assert CloudVoiceStore(tmp_path).load().pending_cleanup == [
        {"kind": "voice", "remote_id": client.created_voice_id},
        {"kind": "file", "remote_id": "1234"},
    ]
    assert service.creating is False


async def test_cancellation_after_activation_never_deletes_the_active_candidate(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    cleanup_started = asyncio.Event()

    class BlockingFileDeleteClient(RecordingMiniMaxClient):
        async def delete_file(self, _file_id):
            self.calls.append("delete_file")
            cleanup_started.set()
            await asyncio.Future()

    client = BlockingFileDeleteClient()
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)
    task = asyncio.create_task(service.create_reference(b"source", "sample.wav", "audio/wav"))
    await cleanup_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    assert store.load().voice_id == client.created_voice_id
    assert "delete_candidate_voice" not in client.calls
    assert client.calls[-1] == "delete_old_voice"
    assert store.load().pending_cleanup == [{"kind": "file", "remote_id": "1234"}]
    assert service.creating is False


async def test_create_reference_records_failed_old_voice_cleanup(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    client = RecordingMiniMaxClient(failed_voice_ids={"oldvoice1234"})
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    await service.create_reference(b"new-source", "recording.wav", "audio/wav")

    assert store.load().pending_cleanup == [
        {"kind": "voice", "remote_id": "oldvoice1234"}
    ]


async def test_retry_cleanup_keeps_only_failed_entries(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    store.replace_pending_cleanup(
        [
            {"kind": "file", "remote_id": "1234"},
            {"kind": "voice", "remote_id": "failedvoice1234"},
        ]
    )
    client = RecordingMiniMaxClient(failed_voice_ids={"failedvoice1234"})
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    await service.retry_cleanup()

    assert store.load().pending_cleanup == [
        {"kind": "voice", "remote_id": "failedvoice1234"}
    ]


async def test_speak_raises_when_no_cloud_voice_is_active(tmp_path):
    service = MiniMaxTTSService(
        tmp_path, "default", minimax_config(), client=RecordingMiniMaxClient()
    )

    with pytest.raises(VoiceUnavailable, match="尚未创建 MiniMax 云端音色"):
        async for _chunk in service.speak("你好"):
            pass


async def test_speak_delegates_active_voice_model_and_instruction(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(old_profile(), b"old", valid_wav())
    client = RecordingMiniMaxClient()
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    chunks = [
        chunk
        async for chunk in service.speak("你好", TTSConfig(instruct_text="开心地说"))
    ]

    assert chunks == [valid_wav()]
    assert client.synthesis_requests == [
        ("你好", "oldvoice1234", "speech-2.8-hd", "开心地说")
    ]


async def test_aclose_closes_the_client(tmp_path):
    client = RecordingMiniMaxClient()
    service = MiniMaxTTSService(tmp_path, "default", minimax_config(), client=client)

    await service.aclose()

    assert client.closed is True


@pytest.mark.parametrize(
    "soul_id",
    ["123 numeric", "_-symbol", "灵魂 / default!", "x" * 400],
)
async def test_create_reference_builds_a_valid_bounded_provider_voice_id(tmp_path, soul_id):
    client = RecordingMiniMaxClient()
    service = MiniMaxTTSService(tmp_path, soul_id, minimax_config(), client=client)

    await service.create_reference(b"source", "recording.wav", "audio/wav")

    assert client.created_voice_id.isascii()
    assert 8 <= len(client.created_voice_id) <= 256
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9]", client.created_voice_id)


async def test_disabled_service_rejects_cloud_reference_creation(tmp_path):
    service = DisabledVoiceService(tmp_path)

    with pytest.raises(VoiceUnavailable, match="语音组件未安装"):
        await service.create_reference(b"source", "recording.wav", "audio/wav")


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("压低声音耳语", "whisper"),
        ("开心而温柔地说", "happy"),
        ("悲伤、低落地说", "sad"),
        ("愤怒地说", "angry"),
        ("恐惧地说", "fearful"),
        ("厌恶地说", "disgusted"),
        ("惊讶地说", "surprised"),
        ("平静自然地说", "calm"),
        ("没有已知标签", "calm"),
    ],
)
def test_instruction_to_emotion(instruction, expected):
    assert instruction_to_emotion(instruction) == expected


async def test_synthesize_decodes_wav_hex():
    wav = valid_wav()

    async def handler(request):
        body = json.loads(request.content)
        assert request.method == "POST"
        assert request.url.path == "/v1/t2a_v2"
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["model"] == "speech-2.8-hd"
        assert body["voice_setting"]["voice_id"] == "heavenvoice1"
        assert body["voice_setting"]["emotion"] == "happy"
        assert body["audio_setting"] == {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "wav",
            "channel": 1,
        }
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "data": {"audio": wav.hex(), "status": 2},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    client = make_client(handler)
    try:
        assert await client.synthesize(
            "你好", "heavenvoice1", "speech-2.8-hd", "开心地说"
        ) == wav
    finally:
        await client.aclose()


async def test_upload_clone_audio_uses_required_multipart_contract():
    async def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/v1/files/upload"
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert b'name="purpose"' in request.content
        assert b"voice_clone" in request.content
        assert b'filename="sample.wav"' in request.content
        assert b"audio/wav" in request.content
        return httpx.Response(
            200,
            json={
                "file": {"file_id": 1234},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    client = make_client(handler)
    try:
        assert await client.upload_clone_audio(b"not-real-audio", "sample.wav", "audio/wav") == 1234
    finally:
        await client.aclose()


async def test_clone_voice_uses_file_voice_and_model():
    async def handler(request):
        assert request.url.path == "/v1/voice_clone"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "file_id": 1234,
            "voice_id": "heavenvoice1",
            "model": "speech-2.8-hd",
        }
        return httpx.Response(200, json={"base_resp": {"status_code": 0}})

    client = make_client(handler)
    try:
        assert await client.clone_voice(1234, "heavenvoice1", "speech-2.8-hd") is None
    finally:
        await client.aclose()


async def test_test_connection_posts_all_voice_type():
    async def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/v1/get_voice"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {"voice_type": "all"}
        return httpx.Response(200, json={"base_resp": {"status_code": 0}})

    client = make_client(handler)
    try:
        assert await client.test_connection() is True
    finally:
        await client.aclose()


async def test_delete_file_uses_voice_clone_purpose():
    async def handler(request):
        assert request.url.path == "/v1/files/delete"
        assert json.loads(request.content) == {"file_id": 1234, "purpose": "voice_clone"}
        return httpx.Response(200, json={"base_resp": {"status_code": 0}})

    client = make_client(handler)
    try:
        assert await client.delete_file(1234) is None
    finally:
        await client.aclose()


async def test_delete_voice_uses_voice_cloning_type():
    async def handler(request):
        assert request.url.path == "/v1/delete_voice"
        assert json.loads(request.content) == {
            "voice_id": "heavenvoice1",
            "voice_type": "voice_cloning",
        }
        return httpx.Response(200, json={"base_resp": {"status_code": 0}})

    client = make_client(handler)
    try:
        assert await client.delete_voice("heavenvoice1") is None
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("status_code", "message", "retryable"),
    [
        (1001, "MiniMax 请求超时，请稍后重试", True),
        (1002, "MiniMax 请求频率受限，请稍后重试", True),
        (1024, "MiniMax 服务暂时不可用，请稍后重试", True),
        (1004, "MiniMax API Key 无效或无权限", False),
        (1008, "MiniMax 账户余额不足", False),
        (9999, "MiniMax 语音服务调用失败", False),
    ],
)
async def test_provider_status_failure_is_safely_mapped(
    status_code, message, retryable
):
    async def handler(request):
        return httpx.Response(
            200,
            json={"base_resp": {"status_code": status_code, "status_msg": "provider detail"}},
        )

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match=message) as error:
            await client.test_connection()
        assert error.value.retryable is retryable
        assert "provider detail" not in str(error.value)
    finally:
        await client.aclose()


@pytest.mark.parametrize("status_code", [True, False, 0.0, "0", None])
async def test_provider_status_rejects_malformed_success_codes(status_code):
    async def handler(_request):
        return httpx.Response(200, json={"base_resp": {"status_code": status_code}})

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="MiniMax 语音服务调用失败") as error:
            await client.test_connection()
        assert error.value.retryable is False
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_http_failures_are_mapped(status):
    async def handler(request):
        return httpx.Response(status, text="provider detail")

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="MiniMax API Key 无效或无权限") as error:
            await client.test_connection()
        assert error.value.retryable is False
        assert "provider detail" not in str(error.value)
    finally:
        await client.aclose()


async def test_rate_limit_is_retryable():
    async def handler(request):
        return httpx.Response(429, text="provider detail")

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="MiniMax 请求频率或额度受限") as error:
            await client.test_connection()
        assert error.value.retryable is True
    finally:
        await client.aclose()


@pytest.mark.parametrize(("status", "retryable"), [(400, False), (500, True)])
async def test_other_http_failures_have_safe_retryability(status, retryable):
    async def handler(request):
        return httpx.Response(status, text="provider detail")

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="MiniMax 语音服务调用失败") as error:
            await client.test_connection()
        assert error.value.retryable is retryable
        assert "provider detail" not in str(error.value)
    finally:
        await client.aclose()


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timed out"), httpx.ConnectError("offline")])
async def test_timeout_and_network_failures_are_retryable(failure):
    async def handler(request):
        raise failure

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="无法连接 MiniMax 语音服务") as error:
            await client.test_connection()
        assert error.value.retryable is True
        assert "timed out" not in str(error.value)
        assert "offline" not in str(error.value)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "audio",
    [
        "",
        "not-hex",
        (b"RIFF" + b"\x00" * 39).hex(),
        (b"NOPE" + b"\x00" * 40).hex(),
    ],
)
async def test_synthesize_rejects_invalid_wav(audio):
    async def handler(request):
        return httpx.Response(
            200,
            json={
                "data": {"audio": audio, "status": 2},
                "base_resp": {"status_code": 0},
            },
        )

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="MiniMax 返回的语音无效") as error:
            await client.synthesize("text", "heavenvoice1", "speech-2.8-hd", "")
        assert error.value.retryable is True
    finally:
        await client.aclose()


async def test_synthesize_rejects_a_structurally_valid_zero_frame_wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)

    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "data": {"audio": buffer.getvalue().hex(), "status": 2},
                "base_resp": {"status_code": 0},
            },
        )

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="MiniMax 返回的语音无效"):
            await client.synthesize("text", "heavenvoice1", "speech-2.8-hd", "")
    finally:
        await client.aclose()


@pytest.mark.parametrize("corrupt", ["signature", "size"])
async def test_synthesize_rejects_malformed_riff(corrupt):
    malformed = bytearray(valid_wav())
    if corrupt == "signature":
        malformed[8:12] = b"NOPE"
    else:
        malformed[4:8] = (len(malformed) + 1).to_bytes(4, "little")

    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "data": {"audio": bytes(malformed).hex(), "status": 2},
                "base_resp": {"status_code": 0},
            },
        )

    client = make_client(handler)
    try:
        with pytest.raises(MiniMaxError, match="MiniMax 返回的语音无效"):
            await client.synthesize("text", "heavenvoice1", "speech-2.8-hd", "")
    finally:
        await client.aclose()
