"""Provider-neutral validation for WAV responses returned by TTS services."""

from __future__ import annotations

import io
import struct
import wave


def validate_wav_structure(audio: bytes) -> None:
    """Raise ValueError when *audio* is not a complete, non-empty RIFF WAV."""
    try:
        if (
            len(audio) < 44
            or not audio.startswith(b"RIFF")
            or audio[8:12] != b"WAVE"
            or struct.unpack("<I", audio[4:8])[0] != len(audio) - 8
        ):
            raise ValueError("invalid RIFF header")
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            if (
                wav_file.getnchannels() < 1
                or wav_file.getsampwidth() < 1
                or wav_file.getframerate() < 1
                or wav_file.getnframes() < 1
            ):
                raise ValueError("invalid WAV parameters")
            expected_frame_bytes = (
                wav_file.getnframes()
                * wav_file.getnchannels()
                * wav_file.getsampwidth()
            )
            if len(wav_file.readframes(wav_file.getnframes())) != expected_frame_bytes:
                raise ValueError("truncated WAV data")
    except (EOFError, OSError, ValueError, wave.Error, struct.error) as exc:
        raise ValueError("invalid WAV") from exc
