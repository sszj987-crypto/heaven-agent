from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
import json

from ..agent.context import TTSConfig
from ..config.logger import get_logger
from ..services.container import ApplicationContainer
from ..voice.asr import create_asr_service
from ..voice.service import VoiceUnavailable
from ..voice.minimax import MiniMaxError
from .dependencies import MAX_AUDIO_UPLOAD_BYTES, get_container
from .schemas import (
    AudioRequest,
    ChatHistoryView,
    ChatRequest,
    ChatResponse,
    MemoryReference,
    RecoverableDeleteView,
)


router = APIRouter()
log = get_logger("api.chat")


@router.get("/chat/history", response_model=ChatHistoryView)
async def get_chat_history(container: ApplicationContainer = Depends(get_container)):
    history = container.agent_loop.messages
    log.info("对话历史返回, messages=%d", len(history))
    return {"messages": history}


@router.delete("/chat/history", response_model=RecoverableDeleteView)
async def delete_chat_history(container: ApplicationContainer = Depends(get_container)):
    loop = container.agent_loop
    async with container.soul_lock:
        async with loop._turn_lock:
            archived = container.data_management.archive_conversation(
                container.memory_store,
                container.candidates,
            )
            loop.delete_history()
    log.info("会话已归档: %s", archived)
    return {"status": "ok", "recoverable": True, "archive": archived.name}


@router.post("/chat", response_model=ChatResponse)
async def chat_text(
    body: ChatRequest,
    container: ApplicationContainer = Depends(get_container),
):
    user_message = body.message.strip()
    _require_llm_settings(container)
    try:
        ctx = await container.agent_loop.run_once(user_message)
    except Exception as exc:
        raise _llm_http_error(exc) from exc

    response_text = ctx.response
    instruct_text = ctx.instruct_text or "用平静自然的语气说话。"
    return ChatResponse(
        response_text=response_text,
        instruct_text=instruct_text,
        has_voice=_voice_available(container),
        used_memories=_memory_references(ctx.retrieved_memories),
        safety_state=ctx.safety_state,
    )


@router.post("/chat/stream")
async def chat_text_stream(
    body: ChatRequest,
    container: ApplicationContainer = Depends(get_container),
):
    """Return reply text as SSE while retaining the normal completed-turn flow."""
    user_message = body.message.strip()
    _require_llm_settings(container)

    async def events():
        try:
            async for event in container.agent_loop.stream_once(user_message):
                if event["type"] == "done":
                    ctx = event["context"]
                    payload = {
                        "type": "done",
                        "response_text": ctx.response,
                        "instruct_text": ctx.instruct_text or "用平静自然的语气说话。",
                        "has_voice": _voice_available(container),
                        "used_memories": _memory_references(ctx.retrieved_memories),
                        "safety_state": ctx.safety_state,
                    }
                else:
                    payload = event
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error = _llm_http_error(exc)
            yield f"data: {json.dumps({'type': 'error', 'message': error.detail}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/voice", response_model=ChatResponse)
async def chat_voice(
    audio: UploadFile = File(...),
    container: ApplicationContainer = Depends(get_container),
):
    if not container.voice_installed:
        raise HTTPException(status_code=503, detail="语音组件未安装，请使用文字对话或安装语音组件")
    _require_llm_settings(container)

    audio_bytes = await audio.read(MAX_AUDIO_UPLOAD_BYTES + 1)
    if len(audio_bytes) > MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="音频不能超过 25 MB")
    try:
        text = await create_asr_service().transcribe(audio_bytes)
    except Exception as exc:
        log.error("ASR 识别失败, error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="语音识别失败，请稍后重试") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="未能识别到语音内容，请重试")

    if hasattr(container.voice, "unavailable_reason"):
        raise HTTPException(status_code=503, detail=container.voice.unavailable_reason)
    try:
        ctx = await container.agent_loop.run_once(text)
    except Exception as exc:
        raise _llm_http_error(exc) from exc

    response_text = ctx.response
    instruct_text = ctx.instruct_text or "用平静自然的语气说话。"
    return ChatResponse(
        response_text=response_text,
        instruct_text=instruct_text,
        has_voice=_voice_available(container),
        transcript=text,
        used_memories=_memory_references(ctx.retrieved_memories),
        safety_state=ctx.safety_state,
    )


@router.post("/chat/audio")
async def chat_audio(
    body: AudioRequest,
    container: ApplicationContainer = Depends(get_container),
):
    if container.settings.tts.provider == "minimax":
        # Select the service only after locking: a queued settings update may
        # have replaced it. Upload/settings use this same lock before deletion.
        async with container.soul_lock:
            return await _chat_audio_response(body, container)
    return await _chat_audio_response(body, container)


async def _chat_audio_response(body: AudioRequest, container: ApplicationContainer):
    tts = container.voice
    if (
        container.settings.tts.provider == "minimax"
        and not container.settings.tts.minimax.api_key
    ):
        raise HTTPException(status_code=400, detail="请先在设置中配置 MiniMax API Key")
    if hasattr(tts, "unavailable_reason"):
        raise HTTPException(status_code=503, detail=tts.unavailable_reason)
    tts_config = TTSConfig(instruct_text=body.instruct_text)
    audio = await _generate_audio(tts, body.text, tts_config)
    return Response(content=audio, media_type="audio/wav")


async def _generate_audio(tts, text: str, config: TTSConfig) -> bytes:
    chunks: list[bytes] = []
    try:
        async for chunk in tts.speak(text, config):
            if chunk:
                chunks.append(chunk)
    except VoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="语音组件当前不可用") from exc
    except MiniMaxError:
        raise
    except ModuleNotFoundError as exc:
        log.exception("TTS 缺少运行依赖, module=%s", exc.name)
        raise HTTPException(
            status_code=503,
            detail=f"缺少语音依赖 {exc.name or '未知模块'}，请运行 python3 scripts/bootstrap.py --voice 后重启服务",
        ) from exc
    except Exception as exc:
        log.exception("TTS 音频生成失败, error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="语音准备失败，请重试") from exc

    audio = b"".join(chunks)
    if not audio:
        raise HTTPException(status_code=500, detail="语音准备失败，请重试")
    return audio


def _require_llm_settings(container: ApplicationContainer) -> None:
    settings = container.settings
    if not settings.llm.api_key or not settings.llm.base_url:
        raise HTTPException(
            status_code=400,
            detail="请先在设置页面配置 LLM 参数（Base URL、API Key、Model）",
        )


def _voice_available(container: ApplicationContainer) -> bool:
    if (
        container.settings.tts.provider == "minimax"
        and not container.settings.tts.minimax.api_key
    ):
        return False
    return bool(container.voice.has_reference)


def _llm_http_error(exc: Exception) -> HTTPException:
    reason = str(exc)
    log.error("LLM 调用失败, error_type=%s", type(exc).__name__)
    if "404" in reason or "Not Found" in reason:
        detail = "LLM 接口地址错误（404），请检查 Base URL 是否正确。DeepSeek 用户请填写 https://api.deepseek.com，OpenAI 用户请填写 https://api.openai.com/v1"
    elif "401" in reason or "Unauthorized" in reason:
        detail = "LLM API Key 无效（401），请检查设置中的 API Key 是否正确"
    elif "Connection" in reason or "connect" in reason or "Name or service not known" in reason:
        detail = "无法连接 LLM 服务，请检查 Base URL 地址和网络连接"
    else:
        detail = "LLM 服务暂时不可用，请稍后重试"
    return HTTPException(status_code=502, detail=detail)


def _memory_references(memories: list[dict]) -> list[MemoryReference]:
    return [
        MemoryReference(
            id=item.get("id", ""),
            content=item.get("document", ""),
            dimension=item.get("metadata", {}).get("dimension", ""),
            source_type=item.get("metadata", {}).get(
                "source_type",
                item.get("metadata", {}).get("type", "unknown"),
            ),
        )
        for item in memories
    ]
