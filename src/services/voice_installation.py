from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from ..data.files import atomic_write_text
from .jobs import Job, JobManager


VoiceInstallState = Literal[
    "not_installed",
    "installing",
    "restart_required",
    "installed",
    "failed",
]


class VoiceInstallationInProgress(RuntimeError):
    pass


class VoiceAlreadyInstalled(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceInstallationStatus:
    state: VoiceInstallState
    stage: str
    message: str
    restart_required: bool = False
    job_id: str | None = None


Runner = Callable[[Path], Awaitable[None]]


class VoiceInstallationService:
    def __init__(
        self,
        *,
        root: Path,
        data_root: Path,
        jobs: JobManager,
        voice_installed: bool,
        runner: Runner | None = None,
    ):
        self._root = Path(root).resolve()
        self._status_path = Path(data_root) / "system" / "voice-installation.json"
        self._jobs = jobs
        self._voice_installed = voice_installed
        self._runner = runner or self._run_bootstrap
        self._job_id: str | None = None

    def status(self) -> VoiceInstallationStatus:
        if self._voice_installed:
            return VoiceInstallationStatus(
                state="installed",
                stage="complete",
                message="语音组件已安装",
            )

        stored = self._read()
        if stored is None:
            return VoiceInstallationStatus(
                state="not_installed",
                stage="idle",
                message="语音组件未安装",
            )

        job_id = stored.job_id or self._job_id
        if stored.state == "installing" and not self._job_active(job_id):
            return VoiceInstallationStatus(
                state="failed",
                stage="interrupted",
                message="上次安装已中断，可以重试",
                job_id=job_id,
            )
        return VoiceInstallationStatus(
            state=stored.state,
            stage=stored.stage,
            message=stored.message,
            restart_required=stored.restart_required,
            job_id=job_id,
        )

    def start(self) -> Job:
        current = self.status()
        if current.state == "installing":
            raise VoiceInstallationInProgress("voice installation is already running")
        if current.state == "installed":
            raise VoiceAlreadyInstalled("voice installation is already complete")

        self._write(
            VoiceInstallationStatus(
                state="installing",
                stage="queued",
                message="语音组件安装任务已创建",
            )
        )
        job = self._jobs.submit("voice_install", self._install())
        self._job_id = job.id
        self._write(
            VoiceInstallationStatus(
                state="installing",
                stage="queued",
                message="语音组件安装任务已创建",
                job_id=job.id,
            )
        )
        return job

    async def _install(self) -> None:
        try:
            await self._runner(self._status_path)
        except asyncio.CancelledError:
            self._write(
                VoiceInstallationStatus(
                    state="failed",
                    stage="interrupted",
                    message="安装已中断，可以重试",
                    job_id=self._job_id,
                )
            )
            raise
        except Exception as exc:
            self._write(
                VoiceInstallationStatus(
                    state="failed",
                    stage="failed",
                    message=self._sanitize_error(exc),
                    job_id=self._job_id,
                )
            )
            raise
        self._write(
            VoiceInstallationStatus(
                state="restart_required",
                stage="complete",
                message="语音组件已安装，请重启 Heaven Agent 生效",
                restart_required=True,
                job_id=self._job_id,
            )
        )

    async def _run_bootstrap(self, status_path: Path) -> None:
        command = [
            sys.executable,
            str(self._root / "scripts" / "bootstrap.py"),
            "--voice",
            "--skip-node",
            "--status-file",
            str(status_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self._root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            process.terminate()
            await process.wait()
            raise
        if process.returncode:
            raw = stderr or stdout or "安装进程没有返回错误信息".encode()
            raise RuntimeError(raw.decode("utf-8", errors="replace")[-2_000:])

    def _job_active(self, job_id: str | None) -> bool:
        if not job_id:
            return False
        try:
            return self._jobs.get(job_id).status in {"pending", "running"}
        except KeyError:
            return False

    def _read(self) -> VoiceInstallationStatus | None:
        if not self._status_path.exists():
            return None
        try:
            payload = json.loads(self._status_path.read_text(encoding="utf-8"))
            return VoiceInstallationStatus(**payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def _write(self, status: VoiceInstallationStatus) -> None:
        atomic_write_text(
            self._status_path,
            json.dumps(asdict(status), ensure_ascii=False, indent=2),
        )

    def _sanitize_error(self, exc: Exception) -> str:
        original = str(exc)
        redacted = original.replace(str(self._root), "<project>")
        redacted = re.sub(
            r"(https?://)[^/\s:@]+:[^@\s/]+@",
            r"\1***@",
            redacted,
        )
        redacted = re.sub(
            r"\b(?:sk-[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9]{8,})",
            "<redacted>",
            redacted,
        )
        detail = redacted[-500:].strip()
        if str(self._root) in original and "<project>" not in detail:
            detail = f"<project> … {detail[-488:]}"
        return f"安装失败：{detail or type(exc).__name__}"
