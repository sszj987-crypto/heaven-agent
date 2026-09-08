import asyncio

import pytest

from src.services.jobs import JobManager
from src.services.voice_installation import (
    VoiceInstallationInProgress,
    VoiceInstallationService,
)


async def test_successful_install_requires_restart(tmp_path):
    jobs = JobManager()

    async def succeed(_status_path):
        return None

    service = VoiceInstallationService(
        root=tmp_path,
        data_root=tmp_path / "data",
        jobs=jobs,
        voice_installed=False,
        runner=succeed,
    )

    job = service.start()
    await jobs.wait(job.id)

    status = service.status()
    assert status.state == "restart_required"
    assert status.restart_required is True
    assert status.job_id == job.id


async def test_failed_install_exposes_only_bounded_error_summary(tmp_path):
    jobs = JobManager()
    private_path = str(tmp_path / "private" / "person")

    async def fail(_status_path):
        raise RuntimeError(private_path + " " + "resolver output " * 200)

    service = VoiceInstallationService(
        root=tmp_path,
        data_root=tmp_path / "data",
        jobs=jobs,
        voice_installed=False,
        runner=fail,
    )

    job = service.start()
    await jobs.wait(job.id)

    status = service.status()
    assert status.state == "failed"
    assert private_path not in status.message
    assert "<project>" in status.message
    assert len(status.message) <= 600


async def test_failed_install_redacts_package_credentials_and_tokens(tmp_path):
    jobs = JobManager()

    async def fail(_status_path):
        raise RuntimeError(
            "https://alice:private-password@packages.example/simple "
            "sk-abcdefghijk123456 hf_abcdefghijk123456"
        )

    service = VoiceInstallationService(
        root=tmp_path,
        data_root=tmp_path / "data",
        jobs=jobs,
        voice_installed=False,
        runner=fail,
    )
    job = service.start()
    await jobs.wait(job.id)

    message = service.status().message
    assert "private-password" not in message
    assert "sk-abcdefghijk123456" not in message
    assert "hf_abcdefghijk123456" not in message


async def test_second_active_install_is_rejected(tmp_path):
    jobs = JobManager()
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait_for_release(_status_path):
        started.set()
        await release.wait()

    service = VoiceInstallationService(
        root=tmp_path,
        data_root=tmp_path / "data",
        jobs=jobs,
        voice_installed=False,
        runner=wait_for_release,
    )
    job = service.start()
    await started.wait()

    with pytest.raises(VoiceInstallationInProgress):
        service.start()

    release.set()
    await jobs.wait(job.id)


def test_restarted_installed_container_reports_installed(tmp_path):
    service = VoiceInstallationService(
        root=tmp_path,
        data_root=tmp_path / "data",
        jobs=JobManager(),
        voice_installed=True,
    )

    status = service.status()

    assert status.state == "installed"
    assert status.restart_required is False
    assert status.message == "语音组件已安装"
