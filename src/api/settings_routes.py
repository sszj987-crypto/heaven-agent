from copy import deepcopy
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..config.logger import get_logger
from ..llm.manager import LLMManager
from ..services.container import ApplicationContainer, _create_selected_voice
from ..voice.minimax import MiniMaxClient, MiniMaxError
from ..voice.openai_compatible import OpenAICompatibleTTSClient
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
            "provider": settings.llm.provider,
            "cloud": {
                "base_url": settings.llm.cloud.base_url,
                "model": settings.llm.cloud.model,
                "temperature": settings.llm.cloud.temperature,
                "api_key_configured": bool(settings.llm.cloud.api_key),
            },
            "ollama": {
                "base_url": settings.llm.ollama.base_url,
                "model": settings.llm.ollama.model,
                "temperature": settings.llm.ollama.temperature,
            },
        },
        "tts": {
            "provider": settings.tts.provider,
            "auto_play": settings.tts.auto_play,
            "audio_cache_size": settings.tts.audio_cache_size,
            "minimax": {
                "base_url": settings.tts.minimax.base_url,
                "model": settings.tts.minimax.model,
                "api_key_configured": bool(settings.tts.minimax.api_key),
            },
            "openai_compatible": {
                "base_url": settings.tts.openai_compatible.base_url,
                "model": settings.tts.openai_compatible.model,
                "voice": settings.tts.openai_compatible.voice,
                "api_key_configured": bool(settings.tts.openai_compatible.api_key),
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
        cloud_update = {
            **{key: value for key, value in llm_update.items() if key in ("base_url", "api_key", "model", "temperature")},
            **(llm_update.get("cloud") or {}),
        }
        candidate_config = deepcopy(settings.llm)
        if llm_update.get("provider") is not None:
            candidate_config.provider = llm_update["provider"]
        for key, value in cloud_update.items():
            if key == "api_key" and value in (None, "***"):
                continue
            if value is not None:
                setattr(candidate_config.cloud, key, value)
        for key, value in (llm_update.get("ollama") or {}).items():
            if value is not None:
                setattr(candidate_config.ollama, key, value)
        try:
            replacement = LLMManager.get_client(candidate_config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            if any(key in llm_update for key in ("provider", "cloud", "ollama")):
                settings.update_llm(
                    provider=llm_update.get("provider"),
                    cloud=cloud_update or None,
                    ollama=llm_update.get("ollama"),
                )
            else:
                # Keep the pre-provider request shape functional for integrations.
                settings.update_llm(**cloud_update)
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
                openai_update = {
                    key: value
                    for key, value in (tts_update.get("openai_compatible") or {}).items()
                    if value is not None
                }
                provider_changed = (
                    tts_update.get("provider") is not None
                    and tts_update["provider"] != settings.tts.provider
                )
                minimax_changed = any(
                    value != getattr(settings.tts.minimax, key)
                    for key, value in minimax_update.items()
                )
                openai_changed = any(
                    value != getattr(settings.tts.openai_compatible, key)
                    for key, value in openai_update.items()
                )
                if provider_changed or minimax_changed or openai_changed:
                    candidate_tts = deepcopy(settings.tts)
                    if tts_update.get("provider") is not None:
                        candidate_tts.provider = tts_update["provider"]
                    for key, value in minimax_update.items():
                        setattr(candidate_tts.minimax, key, value)
                    for key, value in openai_update.items():
                        setattr(candidate_tts.openai_compatible, key, value)
                    replacement = _create_selected_voice(
                        SimpleNamespace(tts=candidate_tts),
                        container.layout.voice_dir,
                        container.root,
                        settings.soul_id,
                    )
                    try:
                        update_kwargs = {
                            "provider": tts_update.get("provider"),
                            "minimax": minimax_update or None,
                            "auto_play": tts_update.get("auto_play"),
                            "audio_cache_size": tts_update.get("audio_cache_size"),
                        }
                        if openai_update:
                            update_kwargs["openai_compatible"] = openai_update
                        settings.update_tts(**update_kwargs)
                    except Exception:
                        try:
                            await replacement.aclose()
                        except Exception:
                            log.warning("未采用的语音服务关闭失败")
                        raise
                    await container.replace_voice(replacement)
                elif (tts_update.get("auto_play") is not None
                      or tts_update.get("audio_cache_size") is not None):
                    settings.update_tts(
                        auto_play=tts_update.get("auto_play"),
                        audio_cache_size=tts_update.get("audio_cache_size"),
                    )
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
    if container.settings.tts.provider == "openai_compatible":
        raise HTTPException(
            status_code=400,
            detail="当前 OpenAI 兼容语音服务不支持在应用内创建音色",
        )
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
    provider = settings.tts.provider
    has_reference = bool(voice.has_reference)
    ready = bool(getattr(voice, "is_ready", has_reference))
    capabilities = getattr(voice, "capabilities", None)
    supports_instruction = bool(
        getattr(capabilities, "supports_instruction", getattr(voice, "supports_instruction", False))
    )
    supports_voice_cloning = bool(
        getattr(capabilities, "supports_voice_cloning", provider != "openai_compatible")
    )
    if provider == "local" and not container.voice_installed:
        state, message = "not_installed", "语音组件未安装"
    elif provider == "minimax" and not settings.tts.minimax.api_key:
        state, message = "not_configured", "请先在设置中配置 MiniMax API Key"
    elif provider == "openai_compatible" and not ready:
        state, message = "not_configured", "请先在设置中配置 OpenAI 兼容语音服务"
    elif bool(getattr(voice, "creating", False)):
        state, message = "creating", "正在创建云端音色"
    elif not has_reference and getattr(voice, "last_error", ""):
        state, message = "failed", voice.last_error
    elif ready:
        state, message = (
            "ready",
            "语音服务已就绪" if provider == "openai_compatible" else "音色已就绪",
        )
    else:
        state, message = "no_voice", "尚未创建可用音色"
    return {
        "has_reference": has_reference,
        "ready": ready,
        "supports_instruction": supports_instruction,
        "supports_voice_cloning": supports_voice_cloning,
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
    if settings.tts.provider == "minimax":
        client = MiniMaxClient(settings.tts.minimax.base_url, settings.tts.minimax.api_key)
    else:
        client = OpenAICompatibleTTSClient(
            settings.tts.openai_compatible.base_url,
            settings.tts.openai_compatible.api_key,
        )
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
