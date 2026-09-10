import asyncio
import io
import shutil
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from ..services.container import ApplicationContainer
from .dependencies import get_container
from ..services.voice_installation import (
    VoiceAlreadyInstalled,
    VoiceInstallationInProgress,
)
from .schemas import (
    DemoResetView,
    DiagnosticsView,
    JobAccepted,
    JobView,
    SystemStatus,
    VoiceInstallationView,
)


router = APIRouter()


@router.get("/system/status", response_model=SystemStatus)
async def get_system_status(container: ApplicationContainer = Depends(get_container)):
    return container.status_service.get()


@router.get("/system/voice-installation", response_model=VoiceInstallationView)
async def get_voice_installation(
    container: ApplicationContainer = Depends(get_container),
):
    return asdict(container.voice_installation.status())


@router.post(
    "/system/voice-installation",
    response_model=JobAccepted,
    status_code=202,
)
async def install_voice(
    x_heaven_action: str | None = Header(default=None),
    container: ApplicationContainer = Depends(get_container),
):
    if x_heaven_action != "install-voice":
        raise HTTPException(status_code=403, detail="缺少语音安装确认")
    try:
        job = container.voice_installation.start()
    except VoiceInstallationInProgress:
        raise HTTPException(status_code=409, detail="语音组件正在安装")
    except VoiceAlreadyInstalled:
        raise HTTPException(status_code=409, detail="语音组件已经安装")
    return {"job_id": job.id}


@router.get("/system/diagnostics", response_model=DiagnosticsView)
async def get_system_diagnostics(
    container: ApplicationContainer = Depends(get_container),
):
    return container.data_management.diagnostics(
        voice_installed=container.voice_installed,
        voice_ready=bool(
            getattr(container.voice, "is_ready", container.voice.has_reference)
        ),
        memory_ready=container.memory_store is not None,
        ffmpeg_available=bool(shutil.which("ffmpeg")),
    )


@router.get("/system/export")
async def export_current_soul(
    container: ApplicationContainer = Depends(get_container),
):
    payload = await asyncio.to_thread(container.data_management.export_zip)
    filename = f"heaven-{container.settings.soul_id}.zip"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/system/onboarding/complete", response_model=SystemStatus)
async def complete_onboarding(container: ApplicationContainer = Depends(get_container)):
    async with container.soul_lock:
        current = container.status_service.get()
        if not current.onboarding.profile_ready or not current.onboarding.import_review_ready:
            raise HTTPException(status_code=409, detail="请先完成档案并处理待确认事实")
        container.onboarding.complete()
    return container.status_service.get()


@router.post("/system/onboarding/steps/{step}", response_model=SystemStatus)
async def mark_onboarding_step(
    step: Literal["profile", "import_review", "voice"],
    container: ApplicationContainer = Depends(get_container),
):
    async with container.soul_lock:
        container.onboarding.mark_step(step)
    return container.status_service.get()


@router.post("/system/demo-reset", response_model=DemoResetView)
async def reset_demo(
    x_heaven_action: str | None = Header(default=None),
    container: ApplicationContainer = Depends(get_container),
):
    if x_heaven_action != "demo-reset":
        raise HTTPException(status_code=403, detail="缺少演示数据重置确认")
    backup = await container.reset_demo()
    backup_location = backup.relative_to(container.layout.data_root).as_posix()
    return {"status": "ok", "recoverable": True, "backup": backup_location}


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(job_id: str, container: ApplicationContainer = Depends(get_container)):
    try:
        return JobView(**asdict(container.jobs.get(job_id)))
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
