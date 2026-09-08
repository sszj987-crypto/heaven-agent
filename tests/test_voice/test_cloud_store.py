import hashlib
import json
from dataclasses import asdict

import pytest

from src.voice.cloud_store import CloudVoiceProfile, CloudVoiceStore


def active_profile() -> CloudVoiceProfile:
    return CloudVoiceProfile(
        provider="minimax",
        voice_id="activevoice1234",
        model="speech-2.8-hd",
        created_at="2026-09-03T00:00:00+00:00",
        source_sha256=hashlib.sha256(b"old").hexdigest(),
    )


def test_activation_atomically_persists_metadata_and_audio(tmp_path):
    store = CloudVoiceStore(tmp_path)
    profile = CloudVoiceProfile(
        provider="minimax",
        voice_id="heavendefault1234",
        model="speech-2.8-hd",
        created_at="2026-09-03T00:00:00+00:00",
        source_sha256=hashlib.sha256(b"source").hexdigest(),
    )

    store.activate(profile, b"source", b"RIFFpreview")

    assert store.load().voice_id == "heavendefault1234"
    assert (tmp_path / "reference-cloud.wav").read_bytes() == b"source"
    assert (tmp_path / "activation-preview.wav").read_bytes() == b"RIFFpreview"


def test_failed_candidate_does_not_replace_active_profile(tmp_path):
    store = CloudVoiceStore(tmp_path)
    store.activate(active_profile(), b"old", b"RIFFold")

    store.add_pending_cleanup("voice", "failed-new-voice")

    assert store.load().voice_id == "activevoice1234"
    assert store.load().pending_cleanup == [
        {"kind": "voice", "remote_id": "failed-new-voice"}
    ]


def test_missing_cloud_metadata_returns_empty_profile(tmp_path):
    profile = CloudVoiceStore(tmp_path).load()

    assert profile == CloudVoiceProfile()


def test_corrupt_cloud_metadata_is_reported_as_failed_profile(tmp_path):
    data = asdict(active_profile())
    data["voice_id"] = 123
    (tmp_path / "cloud.json").write_text(
        json.dumps(data),
        encoding="utf-8",
    )

    profile = CloudVoiceStore(tmp_path).load()

    assert profile.last_error == "云端音色状态损坏"


def test_incomplete_cloud_metadata_is_reported_as_failed_profile(tmp_path):
    (tmp_path / "cloud.json").write_text('{"voice_id": "voice"}', encoding="utf-8")

    profile = CloudVoiceStore(tmp_path).load()

    assert profile.last_error == "云端音色状态损坏"


def test_activation_restores_old_audio_when_metadata_publication_fails(tmp_path, monkeypatch):
    store = CloudVoiceStore(tmp_path)
    old_profile = active_profile()
    store.activate(old_profile, b"old-source", b"old-preview")
    next_profile = CloudVoiceProfile(
        provider="minimax",
        voice_id="newvoice1234",
        model="speech-2.8-hd",
        created_at="2026-09-03T00:01:00+00:00",
        source_sha256=hashlib.sha256(b"new-source").hexdigest(),
    )

    def fail_publish(_profile):
        raise OSError("metadata write failed")

    monkeypatch.setattr(store, "_write_profile", fail_publish)

    with pytest.raises(OSError, match="metadata write failed"):
        store.activate(next_profile, b"new-source", b"new-preview")

    assert store.load() == old_profile
    assert (tmp_path / "reference-cloud.wav").read_bytes() == b"old-source"
    assert (tmp_path / "activation-preview.wav").read_bytes() == b"old-preview"
