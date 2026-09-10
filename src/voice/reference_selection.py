"""Temporary, user-reviewed reference clips for local voice cloning."""

from __future__ import annotations

import json
import subprocess
import uuid
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from ..data.files import atomic_write_text


SAMPLE_RATE = 24_000
CLIP_DURATION_SECONDS = 10.0
MAX_CANDIDATES = 3


@dataclass(frozen=True)
class ReferenceClip:
    id: str
    label: str
    start_seconds: float
    duration_seconds: float


class LocalReferenceSelection:
    """Keep only short, reviewable local candidates until the user selects one."""

    def __init__(self, voice_dir: Path):
        self._root = Path(voice_dir) / ".reference-selection"
        self._manifest = self._root / "manifest.json"

    def prepare(self, audio: bytes) -> list[ReferenceClip]:
        self.clear()
        self._root.mkdir(parents=True, exist_ok=True)
        source = self._root / "upload"
        normalized = self._root / "normalized.wav"
        source.write_bytes(audio)
        try:
            self._normalize(source, normalized)
            samples = self._read_samples(normalized)
            if not len(samples):
                raise ValueError("音频中没有可用内容")
            clips = self._write_candidates(samples)
            atomic_write_text(
                self._manifest,
                json.dumps([asdict(clip) for clip in clips], ensure_ascii=False),
            )
            return clips
        finally:
            source.unlink(missing_ok=True)
            normalized.unlink(missing_ok=True)

    def read(self, clip_id: str) -> bytes:
        clip = next((item for item in self.list() if item.id == clip_id), None)
        if clip is None:
            raise ValueError("该参考片段已失效，请重新上传音频")
        path = self._root / f"{clip.id}.wav"
        if not path.is_file():
            raise ValueError("该参考片段已失效，请重新上传音频")
        return path.read_bytes()

    def list(self) -> list[ReferenceClip]:
        if not self._manifest.is_file():
            return []
        try:
            raw = json.loads(self._manifest.read_text(encoding="utf-8"))
            return [ReferenceClip(**item) for item in raw]
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("参考片段状态无效，请重新上传音频") from exc

    def clear(self) -> None:
        if not self._root.exists():
            return
        for path in self._root.iterdir():
            if path.is_file():
                path.unlink()
        self._root.rmdir()

    def _normalize(self, source: Path, destination: Path) -> None:
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(source), "-ar", str(SAMPLE_RATE),
                    "-ac", "1", "-sample_fmt", "s16", str(destination),
                ],
                capture_output=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise ValueError("无法读取该音频，请上传 WAV、MP3 或 M4A 文件") from exc

    @staticmethod
    def _read_samples(path: Path) -> np.ndarray:
        with wave.open(str(path), "rb") as handle:
            if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
                raise ValueError("音频格式转换失败")
            return np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").copy()

    def _write_candidates(self, samples: np.ndarray) -> list[ReferenceClip]:
        window = min(len(samples), int(CLIP_DURATION_SECONDS * SAMPLE_RATE))
        starts = self._choose_starts(samples, window)
        clips: list[ReferenceClip] = []
        for index, start in enumerate(starts, start=1):
            clip_id = uuid.uuid4().hex
            clip_samples = samples[start:start + window]
            self._write_wav(self._root / f"{clip_id}.wav", clip_samples)
            clips.append(ReferenceClip(
                id=clip_id,
                label=f"候选片段 {index}",
                start_seconds=round(start / SAMPLE_RATE, 1),
                duration_seconds=round(len(clip_samples) / SAMPLE_RATE, 1),
            ))
        return clips

    @staticmethod
    def _choose_starts(samples: np.ndarray, window: int) -> list[int]:
        if len(samples) <= window:
            return [0]
        stride = max(int(SAMPLE_RATE * 2), window // 3)
        possible = list(range(0, len(samples) - window + 1, stride))
        if possible[-1] != len(samples) - window:
            possible.append(len(samples) - window)
        ranked = sorted(
            possible,
            key=lambda start: float(np.mean(np.abs(samples[start:start + window]))),
            reverse=True,
        )
        selected: list[int] = []
        for start in ranked:
            if all(abs(start - existing) >= window // 2 for existing in selected):
                selected.append(start)
            if len(selected) == MAX_CANDIDATES:
                break
        return sorted(selected)

    @staticmethod
    def _write_wav(path: Path, samples: np.ndarray) -> None:
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(samples.astype("<i2", copy=False).tobytes())
