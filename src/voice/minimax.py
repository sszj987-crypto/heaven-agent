"""Bounded HTTP adapter for the MiniMax voice APIs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Literal

import httpx

from ..agent.context import TTSConfig
from ..config.loader import MiniMaxConfig
from .cloud_store import CloudVoiceProfile, CloudVoiceStore
from .audio import validate_wav_structure
from .service import VoiceCapabilities, VoiceUnavailable


ACTIVATION_TEXT = "你好，很高兴再次与你说话。"
CREATE_REFERENCE_ERROR = "MiniMax 云端音色创建失败"
log = logging.getLogger(__name__)


def validate_wav(audio: bytes) -> None:
    """Reject incomplete or structurally invalid provider WAV output."""
    try:
        validate_wav_structure(audio)
    except ValueError as exc:
        raise MiniMaxError("MiniMax 返回的语音无效", retryable=True) from exc


class MiniMaxError(Exception):
    """A safe MiniMax failure suitable for surfacing to application code."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def instruction_to_emotion(instruct_text: str) -> str:
    """Convert free-form Chinese instruction text to a MiniMax emotion value."""
    rules = (
        ("whisper", ("耳语", "悄声", "低声", "压低声音", "小声")),
        ("happy", ("开心", "快乐", "高兴", "愉快", "温柔")),
        ("sad", ("悲伤", "伤心", "低落", "难过", "哀伤")),
        ("angry", ("愤怒", "生气", "愤慨", "恼怒")),
        ("fearful", ("恐惧", "害怕", "惊恐", "紧张")),
        ("disgusted", ("厌恶", "嫌恶", "恶心", "反感")),
        ("surprised", ("惊讶", "吃惊", "震惊", "意外")),
        ("calm", ("平静", "自然", "冷静", "平和")),
    )
    for emotion, phrases in rules:
        if any(phrase in instruct_text for phrase in phrases):
            return emotion
    return "calm"


class MiniMaxClient:
    """Minimal asynchronous client for the MiniMax cloning and TTS endpoints."""

    _TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.removesuffix("/")
        self._api_key = api_key
        self._http = client or httpx.AsyncClient(timeout=self._TIMEOUT)

    async def aclose(self) -> None:
        """Close the HTTP pool, including an injected client supplied for testing."""
        await self._http.aclose()

    async def test_connection(self) -> bool:
        await self._request("POST", "/v1/get_voice", json={"voice_type": "all"})
        return True

    async def upload_clone_audio(
        self, audio: bytes, filename: str, content_type: str
    ) -> int:
        payload = await self._request(
            "POST",
            "/v1/files/upload",
            data={"purpose": "voice_clone"},
            files={"file": (filename, audio, content_type)},
        )
        file = payload.get("file") if isinstance(payload, dict) else None
        file_id = file.get("file_id") if isinstance(file, dict) else None
        if isinstance(file_id, bool) or not isinstance(file_id, int):
            raise MiniMaxError("MiniMax 语音服务调用失败")
        return file_id

    async def clone_voice(self, file_id: int, voice_id: str, model: str) -> None:
        await self._request(
            "POST",
            "/v1/voice_clone",
            json={"file_id": file_id, "voice_id": voice_id, "model": model},
        )

    async def synthesize(
        self, text: str, voice_id: str, model: str, instruct_text: str
    ) -> bytes:
        payload = await self._request(
            "POST",
            "/v1/t2a_v2",
            json={
                "model": model,
                "text": text,
                "stream": False,
                "voice_setting": {
                    "voice_id": voice_id,
                    "speed": 1,
                    "vol": 1,
                    "pitch": 0,
                    "emotion": instruction_to_emotion(instruct_text),
                },
                "audio_setting": {
                    "sample_rate": 32000,
                    "bitrate": 128000,
                    "format": "wav",
                    "channel": 1,
                },
                "subtitle_enable": False,
            },
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        encoded_audio = data.get("audio") if isinstance(data, dict) else None
        if not isinstance(encoded_audio, str):
            raise MiniMaxError("MiniMax 返回的语音无效", retryable=True)
        try:
            audio = bytes.fromhex(encoded_audio)
        except ValueError as exc:
            raise MiniMaxError("MiniMax 返回的语音无效", retryable=True) from exc
        validate_wav(audio)
        return audio

    async def delete_file(self, file_id: int) -> None:
        await self._request(
            "POST",
            "/v1/files/delete",
            json={"file_id": file_id, "purpose": "voice_clone"},
        )

    async def delete_voice(self, voice_id: str) -> None:
        await self._request(
            "POST",
            "/v1/delete_voice",
            json={"voice_id": voice_id, "voice_type": "voice_cloning"},
        )

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise MiniMaxError("无法连接 MiniMax 语音服务", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise MiniMaxError("无法连接 MiniMax 语音服务", retryable=True) from exc

        if response.status_code in (401, 403):
            raise MiniMaxError("MiniMax API Key 无效或无权限")
        if response.status_code == 429:
            raise MiniMaxError("MiniMax 请求频率或额度受限", retryable=True)
        if response.status_code >= 400:
            raise MiniMaxError(
                "MiniMax 语音服务调用失败", retryable=response.status_code >= 500
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MiniMaxError("MiniMax 语音服务调用失败") from exc
        if not isinstance(payload, dict):
            raise MiniMaxError("MiniMax 语音服务调用失败")

        base_resp = payload.get("base_resp")
        status_code = base_resp.get("status_code") if isinstance(base_resp, dict) else None
        if type(status_code) is not int:
            raise MiniMaxError("MiniMax 语音服务调用失败")
        if status_code != 0:
            message, retryable = {
                1001: ("MiniMax 请求超时，请稍后重试", True),
                1002: ("MiniMax 请求频率受限，请稍后重试", True),
                1024: ("MiniMax 服务暂时不可用，请稍后重试", True),
                1004: ("MiniMax API Key 无效或无权限", False),
                1008: ("MiniMax 账户余额不足", False),
            }.get(status_code, ("MiniMax 语音服务调用失败", False))
            raise MiniMaxError(message, retryable=retryable)
        return payload


class MiniMaxTTSService:
    """Own the lifecycle of one Soul's MiniMax cloned voice."""

    _CLEANUP_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        data_dir: Path,
        soul_id: str,
        config: MiniMaxConfig,
        client: MiniMaxClient | None = None,
    ):
        self._store = CloudVoiceStore(Path(data_dir))
        self._soul_id = soul_id
        self._config = config
        self._client = client or MiniMaxClient(config.base_url, config.api_key)
        self._creating = False

    @property
    def has_reference(self) -> bool:
        return bool(self._store.load().voice_id)

    @property
    def is_ready(self) -> bool:
        return bool(self._config.api_key and self.has_reference)

    @property
    def capabilities(self) -> VoiceCapabilities:
        return VoiceCapabilities(
            requires_reference=True,
            supports_voice_cloning=True,
            supports_instruction=True,
        )

    @property
    def supports_instruction(self) -> bool:
        return True

    @property
    def activation_preview(self) -> bytes | None:
        if not self.has_reference:
            return None
        return self._store.load_activation_preview()

    @property
    def creating(self) -> bool:
        return self._creating

    @property
    def last_error(self) -> str:
        return self._store.load().last_error

    async def create_reference(
        self, audio: bytes, filename: str, content_type: str
    ) -> bytes:
        """Clone, verify, and atomically activate a new voice for this Soul."""
        old_profile = self._store.load()
        file_id: int | None = None
        candidate_voice_id: str | None = None
        activated = False
        failure: BaseException | None = None
        self._creating = True
        try:
            try:
                file_id = await self._client.upload_clone_audio(
                    audio, filename, content_type
                )
                candidate_voice_id = self._make_voice_id()
                await self._client.clone_voice(
                    file_id, candidate_voice_id, self._config.model
                )
                preview = await self._client.synthesize(
                    ACTIVATION_TEXT, candidate_voice_id, self._config.model, ""
                )
                validate_wav(preview)
                profile = CloudVoiceProfile(
                    provider="minimax",
                    voice_id=candidate_voice_id,
                    model=self._config.model,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source_sha256=hashlib.sha256(audio).hexdigest(),
                    pending_cleanup=list(old_profile.pending_cleanup),
                )
                self._store.activate(profile, audio, preview)
                activated = True
            except BaseException as exc:
                failure = exc
                try:
                    self._store.set_last_error(CREATE_REFERENCE_ERROR)
                except Exception:
                    log.warning("Unable to persist cloud voice failure status")
                raise
            return preview
        finally:
            # Every acquired remote resource gets its own bounded cleanup attempt.
            # Await them here so cancellation cannot leave detached cleanup tasks.
            try:
                cleanup: list[tuple[Literal["file", "voice"], str]] = []
                if not activated and candidate_voice_id is not None:
                    cleanup.append(("voice", candidate_voice_id))
                if file_id is not None:
                    cleanup.append(("file", str(file_id)))
                if activated and old_profile.voice_id and old_profile.voice_id != candidate_voice_id:
                    cleanup.append(("voice", old_profile.voice_id))
                cancellation = None
                for kind, remote_id in cleanup:
                    try:
                        await self._delete_or_queue(kind, remote_id)
                    except asyncio.CancelledError as exc:
                        cancellation = exc
                if cancellation is not None and failure is None:
                    raise cancellation
            finally:
                self._creating = False

    async def retry_cleanup(self) -> None:
        """Retry persisted remote deletes, retaining only operations that still fail."""
        profile = self._store.load()
        remaining: list[dict[str, str]] = []
        for entry in profile.pending_cleanup:
            kind = entry["kind"]
            remote_id = entry["remote_id"]
            try:
                if kind == "file":
                    await self._client.delete_file(int(remote_id))
                elif kind == "voice":
                    await self._client.delete_voice(remote_id)
                else:
                    raise ValueError("unsupported cleanup kind")
            except Exception:
                remaining.append(entry)
        self._store.replace_pending_cleanup(remaining)

    async def speak(
        self, text: str, config: TTSConfig | None = None
    ) -> AsyncGenerator[bytes, None]:
        profile = self._store.load()
        if not profile.voice_id:
            raise VoiceUnavailable("尚未创建 MiniMax 云端音色")
        cfg = config or TTSConfig()
        audio = await self._client.synthesize(
            text, profile.voice_id, profile.model, cfg.instruct_text
        )
        yield audio

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _delete_or_queue(self, kind: Literal["file", "voice"], remote_id: str) -> None:
        try:
            async with asyncio.timeout(self._CLEANUP_TIMEOUT_SECONDS):
                if kind == "file":
                    await self._client.delete_file(int(remote_id))
                else:
                    await self._client.delete_voice(remote_id)
        except (Exception, asyncio.CancelledError) as exc:
            try:
                self._store.add_pending_cleanup(kind, remote_id)
            except Exception:
                log.warning("Unable to persist pending cloud voice cleanup")
            if isinstance(exc, asyncio.CancelledError):
                raise

    def _make_voice_id(self) -> str:
        ascii_soul_id = self._soul_id.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^A-Za-z0-9_-]", "", ascii_soul_id)
        # 7 prefix chars + at most 216 Soul chars + separator + 32 UUID chars.
        return f"heaven-{normalized[:216]}-{uuid.uuid4().hex}"
