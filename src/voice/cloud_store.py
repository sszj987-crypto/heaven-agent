from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ..data.files import atomic_write_bytes, atomic_write_text


CORRUPT_PROFILE_ERROR = "云端音色状态损坏"


@dataclass
class CloudVoiceProfile:
    provider: str = "minimax"
    voice_id: str = ""
    model: str = ""
    created_at: str = ""
    source_sha256: str = ""
    pending_cleanup: list[dict[str, str]] = field(default_factory=list)
    last_error: str = ""


class CloudVoiceStore:
    """Persists one Soul's active cloud voice and cleanup state."""

    def __init__(self, voice_dir: Path):
        self._voice_dir = Path(voice_dir)
        self._metadata_path = self._voice_dir / "cloud.json"
        self._source_path = self._voice_dir / "reference-cloud.wav"
        self._preview_path = self._voice_dir / "activation-preview.wav"

    def load(self) -> CloudVoiceProfile:
        if not self._metadata_path.exists():
            return CloudVoiceProfile()
        try:
            data = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            return _profile_from_data(data)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return CloudVoiceProfile(last_error=CORRUPT_PROFILE_ERROR)

    def activate(self, profile: CloudVoiceProfile, source: bytes, preview: bytes) -> None:
        """Persist audio before publishing the profile that references it."""
        old_source = self._read_optional_bytes(self._source_path)
        old_preview = self._read_optional_bytes(self._preview_path)
        try:
            atomic_write_bytes(self._source_path, source)
            atomic_write_bytes(self._preview_path, preview)
            self._write_profile(profile)
        except Exception:
            self._restore_bytes(self._source_path, old_source)
            self._restore_bytes(self._preview_path, old_preview)
            raise

    def add_pending_cleanup(
        self, kind: Literal["file", "voice"], remote_id: str
    ) -> None:
        profile = self.load()
        profile.pending_cleanup.append({"kind": kind, "remote_id": remote_id})
        self._write_profile(profile)

    def replace_pending_cleanup(self, pending_cleanup: list[dict[str, str]]) -> None:
        """Replace cleanup work after a retry without touching the active voice."""
        profile = self.load()
        profile.pending_cleanup = [dict(item) for item in pending_cleanup]
        self._write_profile(profile)

    def set_last_error(self, message: str) -> None:
        """Persist a caller-supplied safe status message for this Soul voice."""
        profile = self.load()
        profile.last_error = message
        self._write_profile(profile)

    def load_activation_preview(self) -> bytes | None:
        """Return the active preview when it is available locally."""
        try:
            return self._preview_path.read_bytes()
        except OSError:
            return None

    def _write_profile(self, profile: CloudVoiceProfile) -> None:
        atomic_write_text(
            self._metadata_path,
            json.dumps(asdict(profile), ensure_ascii=False, indent=2),
        )

    @staticmethod
    def _read_optional_bytes(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    @staticmethod
    def _restore_bytes(path: Path, previous: bytes | None) -> None:
        if previous is None:
            path.unlink(missing_ok=True)
            return
        atomic_write_bytes(path, previous)


def _profile_from_data(data: object) -> CloudVoiceProfile:
    if not isinstance(data, dict):
        raise ValueError("cloud profile must be an object")
    required_fields = {
        "provider",
        "voice_id",
        "model",
        "created_at",
        "source_sha256",
        "pending_cleanup",
        "last_error",
    }
    if not required_fields.issubset(data):
        raise ValueError("cloud profile is incomplete")

    values = {
        name: _string_field(data, name)
        for name in ("provider", "voice_id", "model", "created_at", "source_sha256", "last_error")
    }
    pending_cleanup = data.get("pending_cleanup", [])
    if not isinstance(pending_cleanup, list):
        raise ValueError("pending_cleanup must be a list")
    if any(
        not isinstance(item, dict)
        or set(item) != {"kind", "remote_id"}
        or not isinstance(item["kind"], str)
        or not isinstance(item["remote_id"], str)
        for item in pending_cleanup
    ):
        raise ValueError("pending_cleanup contains an invalid entry")

    return CloudVoiceProfile(
        **values,
        pending_cleanup=[dict(item) for item in pending_cleanup],
    )


def _string_field(data: dict[object, object], name: str) -> str:
    value = data[name]
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value
