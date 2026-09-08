from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..config.logger import get_logger
from ..llm.manager import LLMManager
from ..services.container import ApplicationContainer, _create_selected_voice
from ..voice.minimax import MiniMaxClient, MiniMaxError
from ..voice.service import VoiceUnavailable
from .dependencies import MAX_AUDIO_UPLOAD_BYTES, get_container
from .schemas import (
    LLMConnectionView,
    SettingsUpdate,
    SettingsView,
    StatusView,
    TTSConnectionView,
    VoiceUploadView,
    VoiceStatusView,
)


router = APIRouter()
log = get_logger("api.settings")


@router.get("/settings", response_model=SettingsView)
async def get_settings(container: ApplicationContainer = Depends(get_container)):
    settings = container.settings
    return {
        "llm": {
            "base_url": settings.llm.base_url,
            "model": settings.llm.model,
            "temperature": settings.llm.temperature,
            "api_key_configured": bool(settings.llm.api_key),
        },
        "tts": {
            "provider": settings.tts.provider,
            "minimax": {
                "base_url": settings.tts.minimax.base_url,
                "model": settings.tts.minimax.model,
                "api_key_configured": bool(settings.tts.minimax.api_key),
            },
        },
        "log_level": settings.log_level,
    }


@router.put("/settings", response_model=StatusView)
async def update_settings(
    body: SettingsUpdate,
    container: ApplicationContainer = Depends(get_container),
):
    settings = container.settings
    if body.llm is not None:
        llm_update = body.llm.model_dump(exclude_unset=True)
        candidate_config = replace(settings.llm)
        for key, value in llm_update.items():
            if key == "api_key" and value in (None, "***"):
                continue
            if value is not None:
                setattr(candidate_config, key, value)
        try:
            replacement = LLMManager.get_client(candidate_config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            settings.update_llm(**llm_update)
        except Exception:
            await replacement.aclose()
            raise
        await container.replace_llm(replacement)
    if body.tts is not None:
        try:
            async with container.soul_lock:
                tts_update = body.tts.model_dump(exclude_unset=True)
                minimax_update = {
                    key: value
                    for key, value in (tts_update.get("minimax") or {}).items()
                    if value is not None
                }
                if tts_update.get("provider") is not None or minimax_update:
                    candidate_tts = deepcopy(settings.tts)
                    if tts_update.get("provider") is not None:
                        candidate_tts.provider = tts_update["provider"]
                    for key, value in minimax_update.items():
                        setattr(candidate_tts.minimax, key, value)
                    replacement = _create_selected_voice(
                        SimpleNamespace(tts=candidate_tts),
                        container.layout.voice_dir,
                        container.root,
                        settings.soul_id,
                    )
                    try:
                        settings.update_tts(
                            provider=tts_update.get("provider"),
                            minimax=minimax_update or None,
                        )
                    except Exception:
                        try:
                            await replacement.aclose()
                        except Exception:
                            log.warning("未采用的语音服务关闭失败")
                        raise
                    await container.replace_voice(replacement)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.log_level is not None:
        settings.update_log_level(body.log_level)
    return {"status": "ok"}


@router.post("/settings/voice/upload", response_model=VoiceUploadView)
async def upload_voice_sample(
    audio: UploadFile = File(...),
    container: ApplicationContainer = Depends(get_container),
):
    audio_bytes = await audio.read(MAX_AUDIO_UPLOAD_BYTES + 1)
    if len(audio_bytes) > MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="音频不能超过 25 MB")
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="音频数据为空")
    try:
        async with container.soul_lock:
            preview = await container.save_voice_reference(
                audio_bytes,
                audio.filename or "reference.wav",
                audio.content_type or "application/octet-stream",
            )
    except VoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MiniMaxError:
        raise
    except Exception as exc:
        log.error("声音档案保存失败, error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="音频保存失败，请稍后重试") from exc
    return {"status": "ok", "preview_available": preview is not None}


@router.get("/settings/voice/status", response_model=VoiceStatusView)
async def get_voice_status(container: ApplicationContainer = Depends(get_container)):
    settings = container.settings
    voice = container.voice
    has_reference = bool(voice.has_reference)
    provider = settings.tts.provider
    if provider == "local" and not container.voice_installed:
        state, message = "not_installed", "语音组件未安装"
    elif provider == "minimax" and not settings.tts.minimax.api_key:
        state, message = "not_configured", "请先在设置中配置 MiniMax API Key"
    elif bool(getattr(voice, "creating", False)):
        state, message = "creating", "正在创建云端音色"
    elif not has_reference and getattr(voice, "last_error", ""):
        state, message = "failed", voice.last_error
    elif has_reference:
        state, message = "ready", "音色已就绪"
    else:
        state, message = "no_voice", "尚未创建可用音色"
    return {
        "has_reference": has_reference,
        "supports_instruction": bool(getattr(voice, "supports_instruction", False)),
        "preview_available": provider == "minimax" and state == "ready"
        and bool(getattr(voice, "activation_preview", None)),
        "provider": provider,
        "state": state,
        "message": message,
    }


@router.post("/settings/test-llm", response_model=LLMConnectionView)
async def test_llm_connection(container: ApplicationContainer = Depends(get_container)):
    return {"connected": await LLMManager.test_connection(container.settings.llm)}


@router.post("/settings/test-tts", response_model=TTSConnectionView)
async def test_tts_connection(container: ApplicationContainer = Depends(get_container)):
    settings = container.settings
    if settings.tts.provider == "local":
        return {"connected": not hasattr(container.voice, "unavailable_reason")}
    client = MiniMaxClient(settings.tts.minimax.base_url, settings.tts.minimax.api_key)
    try:
        return {"connected": await client.test_connection()}
    finally:
        await client.aclose()


@router.get("/settings/voice/preview")
async def get_voice_preview(container: ApplicationContainer = Depends(get_container)):
    if container.settings.tts.provider != "minimax":
        raise HTTPException(status_code=404, detail="当前没有可用的云端音色试听")
    preview = getattr(container.voice, "activation_preview", None)
    if not preview:
        raise HTTPException(status_code=404, detail="当前没有可用的云端音色试听")
    return Response(content=preview, media_type="audio/wav")
