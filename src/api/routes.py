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


# ─── 逝者所在场景（必须在 /soul/{dimension} 之前，避免路由冲突）──

SCENES = {
    "heaven": {
        "label": "天堂",
        "description": "四季如春的宁静世界，有自己的房子，有公园湖泊，有邻居相伴，一切安好",
        "prompt": """# 当前场景

## context
- 所在之地: 天堂
- 场景氛围: 宁静、安详、温暖、自在
- 时间感: 四季如春，阳光明媚的午后

## description
逝者此刻身处天堂——这里四季如春，阳光温暖而不灼热，微风轻柔。睁开眼睛，就来到了这个世界。

这里有一栋属于自己的小房子，不大但很舒适，布置成生前最喜欢的模样。推开门，外面是大片绿色的公园，有人在散步，有人在长椅上晒太阳聊天，远处还有一片湖泊，水面泛着金色的光。

不需要劳动，不需要操劳。饿了，食物就会出现在桌上，且都是自己喜欢的味道。想看书，书就在手边。想念某个人，心里一想，对方的模样就清晰起来。这里有一些邻居，都是和善的人，偶尔串门、一起在公园散步，不会孤单。

这里就像一个温暖的家，没有病痛，没有烦恼，只是安安静静地过日子，等待某天与亲人重逢。
""",
    },
}


@router.get("/soul/circumstances")
async def get_circumstances():
    """返回当前场景内容（可编辑文本）和可选场景列表"""
    current = Settings.get().circumstances
    scene_key = _get_current_scene_key()
    return {
        "content": current,
        "scene": scene_key,
        "scenes": [
            {"key": key, "label": val["label"], "description": val["description"], "prompt": val["prompt"]}
            for key, val in SCENES.items()
        ],
    }


@router.put("/soul/circumstances")
async def update_circumstances(body: dict):
    """更新场景内容（保存原始文本到 circumstances.md）并热更新模块"""
    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="场景内容不能为空")

    settings = Settings.get()
    settings.update_circumstances(content)
    _get_agent_loop().update_circumstances(content)
    return {"status": "ok"}


def _get_current_scene_key() -> str:
    """根据当前 circumstances 内容反向查找场景 key"""
    current = Settings.get().circumstances
    for key, val in SCENES.items():
        if val["prompt"].strip() == current.strip():
            return key
    return "custom" if current else ""


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
    }


@router.put("/settings")
async def update_settings(body: dict):
    settings = Settings.get()
    if "llm" in body:
        settings.update_llm(**body["llm"])
    if "voice" in body:
        settings.update_voice(**body["voice"])
    return {"status": "ok"}


@router.post("/settings/voice/upload")
async def upload_voice_sample(audio: UploadFile = File(...), name: str = "soul_voice"):
    """
    上传参考音频 → Fish Speech 创建声纹克隆 → 返回 speaker_id 并自动保存。
    """
    settings = Settings.get()
    audio_bytes = await audio.read()
    tts = TTSService(settings.voice.fish_speech_url)
    try:
        speaker_id = await tts.create_voice(name, audio_bytes)
    except Exception as e:
        reason = str(e)
        if "502" in reason or "Bad Gateway" in reason:
            detail = "语音服务未启动，请检查语音服务地址是否正确（当前: " + settings.voice.fish_speech_url + "）"
        elif "Connection" in reason or "connect" in reason:
            detail = "无法连接语音服务，请确认服务已启动"
        else:
            detail = "声纹创建失败，请稍后重试"
        raise HTTPException(status_code=502, detail=detail)

    settings.update_voice(speaker=speaker_id)
    return {"status": "ok"}


@router.post("/settings/test-llm")
async def test_llm_connection():
    settings = Settings.get()
    ok = await LLMManager.test_connection(settings.llm)
    return {"connected": ok}
