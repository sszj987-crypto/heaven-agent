import json
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, Response
from ..config.settings import Settings
from ..llm.manager import LLMManager
from ..soul.loader import SoulLoader
from ..agent.loop import AgentLoop
from ..agent.context import TTSConfig
from ..voice.asr import ASRService
from ..voice.tts import TTSService

router = APIRouter()

# 全局单例，启动时初始化
_agent_loop: AgentLoop | None = None
_tts: TTSService | None = None
_soul_loader: SoulLoader | None = None


def init_services():
    """应用启动时调用，初始化全局服务"""
    global _agent_loop, _tts, _soul_loader
    settings = Settings.get()
    llm_client = LLMManager.get_client(settings.llm)
    _soul_loader = SoulLoader(settings.soul_path)
    _tts = TTSService(settings.voice.fish_speech_url)
    _agent_loop = AgentLoop(
        llm_client=llm_client,
        soul_loader=_soul_loader,
        circumstances=settings.circumstances,
    )


def _get_agent_loop() -> AgentLoop:
    assert _agent_loop is not None, "init_services() must be called first"
    return _agent_loop


def _get_tts() -> TTSService:
    assert _tts is not None, "init_services() must be called first"
    return _tts


# ─── 对话路由（统一语音输出） ────────────────────────

@router.post("/chat")
async def chat_text(body: dict):
    """
    文字对话 → 语音输出。
    前端 fetch 音频 blob 后播放。
    """
    user_message = body.get("message", "")
    if not user_message:
        raise HTTPException(status_code=400, detail="Message is required")

    loop = _get_agent_loop()
    tts = _get_tts()

    results = []
    async for item in loop.run(user_message):
        results.append(item)

    response_text = results[0] if results else ""
    tts_config = results[1] if len(results) > 1 else TTSConfig()

    async def audio_stream():
        async for chunk in tts.speak(response_text, tts_config):
            yield chunk

    return StreamingResponse(audio_stream(), media_type="audio/wav",
                             headers={"X-Response-Text": response_text})


@router.post("/chat/voice")
async def chat_voice(audio: UploadFile = File(...)):
    """
    语音对话 → 语音输出。
    """
    settings = Settings.get()
    audio_bytes = await audio.read()
    asr = ASRService(settings.voice.fish_speech_url)

    # ASR: audio → text
    text = await asr.transcribe(audio_bytes)

    loop = _get_agent_loop()
    tts = _get_tts()

    results = []
    async for item in loop.run(text):
        results.append(item)

    response_text = results[0] if results else ""
    tts_config = results[1] if len(results) > 1 else TTSConfig()

    async def audio_stream():
        async for chunk in tts.speak(response_text, tts_config):
            yield chunk

    return StreamingResponse(audio_stream(), media_type="audio/wav",
                             headers={"X-Response-Text": response_text})


# ─── 灵魂管理路由 ──────────────────────────────────────

@router.get("/soul")
async def get_soul():
    profile = _soul_loader.load()
    return {"dimensions": profile.dimensions}


@router.get("/soul/{dimension}")
async def get_dimension(dimension: str):
    content = _soul_loader.load_dimension(dimension)
    return {"dimension": dimension, "content": content}


@router.put("/soul/{dimension}")
async def update_dimension(dimension: str, body: dict):
    content = body.get("content", "")
    _soul_loader.save_dimension(dimension, content)
    _get_agent_loop().invalidate_soul_cache()
    return {"status": "ok"}


# ─── 配置路由 ──────────────────────────────────────────

@router.get("/settings")
async def get_settings():
    settings = Settings.get()
    return {
        "llm": {
            "base_url": settings.llm.base_url,
            "model": settings.llm.model,
            "api_key": "***" if settings.llm.api_key else "",
        },
        "voice": {
            "fish_speech_url": settings.voice.fish_speech_url,
        },
        "circumstances": settings.circumstances,
    }


@router.put("/settings")
async def update_settings(body: dict):
    settings = Settings.get()
    if "llm" in body:
        settings.update_llm(**body["llm"])
    if "voice" in body:
        settings.update_voice(**body["voice"])
    return {"status": "ok"}


@router.post("/settings/test-llm")
async def test_llm_connection():
    settings = Settings.get()
    ok = await LLMManager.test_connection(settings.llm)
    return {"connected": ok}
