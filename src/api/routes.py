import json
import base64
import traceback
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from ..config.settings import Settings
from ..config.logger import get_logger
from ..llm.manager import LLMManager
from ..soul.loader import SoulLoader
from ..agent.loop import AgentLoop
from ..agent.context import TTSConfig
from ..voice.asr import ASRService
from ..voice.tts import TTSService
from ..voice.tts_official import OfficialTTSService
from ..soul.distiller import SoulDistiller
from ..llm.client import LLMClient

router = APIRouter()
log = get_logger("api")

# 全局单例，启动时初始化
_agent_loop: AgentLoop | None = None
_tts: TTSService | OfficialTTSService | None = None
_soul_loader: SoulLoader | None = None
_distiller: SoulDistiller | None = None
_llm_client: LLMClient | None = None


def init_services():
    """应用启动时调用，初始化全局服务"""
    global _agent_loop, _tts, _soul_loader, _distiller, _llm_client
    log.info("正在初始化服务...")
    settings = Settings.get()
    _llm_client = LLMManager.get_client(settings.llm)
    _soul_loader = SoulLoader(settings.soul_path)

    # 根据配置选择 TTS 后端
    _backend = settings.tts_backend
    if _backend == "official":
        log.info("使用官方 CosyVoice PyTorch 后端")
        _tts = OfficialTTSService(settings.data_dir / "voice")
    else:
        log.info("使用 CosyVoice3 MLX 后端")
        _tts = TTSService(settings.data_dir / "voice")

    _distiller = SoulDistiller(_llm_client, _soul_loader)

    _agent_loop = AgentLoop(
        llm_client=_llm_client,
        soul_loader=_soul_loader,
        circumstances=settings.circumstances,
        history_path=str(settings.data_dir / "conversation.json"),
    )

    # 后台预热 TTS 模型，避免首次请求等待模型加载（~30-60s）
    import asyncio
    if _tts.has_reference:
        async def _warm_up():
            try:
                async for _ in _tts.speak("你好"):
                    pass
                log.info("TTS 预热完成")
            except Exception as e:
                log.warning("TTS 预热失败（非致命）: %s", e)
        asyncio.ensure_future(_warm_up())

    log.info("服务初始化完成")


def _get_agent_loop() -> AgentLoop:
    assert _agent_loop is not None, "init_services() must be called first"
    return _agent_loop


def _get_tts() -> TTSService | OfficialTTSService:
    assert _tts is not None, "init_services() must be called first"
    return _tts


# ─── 对话路由（文字即时返回 + 音频独立请求） ────────


@router.get("/chat/history")
async def get_chat_history():
    """返回对话历史（供前端恢复会话）"""
    log.info("获取对话历史")
    loop = _get_agent_loop()
    history = loop.messages
    log.info("对话历史返回, messages=%d", len(history))
    return {"messages": history}


@router.delete("/chat/history")
async def delete_chat_history():
    """删除会话：清空对话历史 + memory daily"""
    loop = _get_agent_loop()
    loop.delete_history()

    # 清理 memory/daily 目录下所有 daily markdown 文件
    import shutil
    from pathlib import Path
    memory_daily = Path(__file__).resolve().parent.parent.parent / "memory" / "daily"
    if memory_daily.exists():
        shutil.rmtree(memory_daily)
        memory_daily.mkdir(parents=True, exist_ok=True)
        log.info("Memory daily 目录已清空: %s", memory_daily)

    log.info("会话已删除")
    return {"status": "ok"}


@router.post("/chat")
async def chat_text(body: dict):
    """
    文字对话 → 即时返回文字 + TTS 配置。
    前端拿到文字后立即显示，再用 /chat/audio 单独获取音频。
    """
    user_message = body.get("message", "")
    if not user_message:
        raise HTTPException(status_code=400, detail="Message is required")

    log.info("收到文字对话请求: %s...", user_message[:50])

    settings = Settings.get()
    if not settings.llm.api_key or not settings.llm.base_url:
        log.error("LLM 未配置，拒绝对话请求")
        raise HTTPException(status_code=400, detail="请先在设置页面配置 LLM 参数（Base URL、API Key、Model）")

    loop = _get_agent_loop()
    tts = _get_tts()

    try:
        results = []
        async for item in loop.run(user_message):
            results.append(item)
        log.debug("AgentLoop 完成，results 数量: %d", len(results))
    except Exception as e:
        reason = str(e)
        log.error("LLM 调用失败: %s\n%s", reason, traceback.format_exc())
        if "404" in reason or "Not Found" in reason:
            detail = "LLM 接口地址错误（404），请检查 Base URL 是否正确。DeepSeek 用户请填写 https://api.deepseek.com，OpenAI 用户请填写 https://api.openai.com/v1"
        elif "401" in reason or "Unauthorized":
            detail = "LLM API Key 无效（401），请检查设置中的 API Key 是否正确"
        elif "Connection" in reason or "connect" in reason or "Name or service not known" in reason:
            detail = "无法连接 LLM 服务，请检查 Base URL 地址和网络连接"
        else:
            detail = f"LLM 调用失败: {reason}"
        raise HTTPException(status_code=502, detail=detail)

    response_text = results[0] if results else ""
    instruct_text = results[1] if len(results) > 1 else "用平静自然的语气说话。"
    log.info("LLM 响应长度: %d 字符, instruct_text=%s",
             len(response_text), instruct_text)
    log.debug("最终响应文本:\n%s", response_text)

    return {
        "response_text": response_text,
        "instruct_text": instruct_text,
        "has_voice": tts.has_reference,
    }


@router.post("/chat/voice")
async def chat_voice(audio: UploadFile = File(...)):
    """
    语音对话 → 即时返回文字 + TTS 配置。
    """
    log.info("收到语音对话请求, filename=%s", audio.filename)

    settings = Settings.get()
    if not settings.llm.api_key or not settings.llm.base_url:
        log.error("LLM 未配置，拒绝语音对话请求")
        raise HTTPException(status_code=400, detail="请先在设置页面配置 LLM 参数（Base URL、API Key、Model）")

    audio_bytes = await audio.read()
    log.debug("语音数据大小: %d bytes", len(audio_bytes))

    asr = ASRService()

    # ASR: audio → text
    try:
        text = await asr.transcribe(audio_bytes)
        log.info("ASR 识别结果: %s...", text[:50])
    except Exception as e:
        log.error("ASR 识别失败: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"语音识别失败: {str(e)}")

    if not text.strip():
        log.warning("ASR 识别为空")
        raise HTTPException(status_code=400, detail="未能识别到语音内容，请重试")

    loop = _get_agent_loop()
    tts = _get_tts()

    try:
        results = []
        async for item in loop.run(text):
            results.append(item)
        log.debug("AgentLoop 完成，results 数量: %d", len(results))
    except Exception as e:
        reason = str(e)
        log.error("LLM 调用失败: %s\n%s", reason, traceback.format_exc())
        if "404" in reason or "Not Found" in reason:
            detail = "LLM 接口地址错误（404），请检查 Base URL 是否正确。DeepSeek 用户请填写 https://api.deepseek.com，OpenAI 用户请填写 https://api.openai.com/v1"
        elif "401" in reason or "Unauthorized":
            detail = "LLM API Key 无效（401），请检查设置中的 API Key 是否正确"
        elif "Connection" in reason or "connect" in reason or "Name or service not known" in reason:
            detail = "无法连接 LLM 服务，请检查 Base URL 地址和网络连接"
        else:
            detail = f"LLM 调用失败: {reason}"
        raise HTTPException(status_code=502, detail=detail)

    response_text = results[0] if results else ""
    instruct_text = results[1] if len(results) > 1 else "用平静自然的语气说话。"
    log.info("LLM 响应长度: %d 字符, instruct_text=%s",
             len(response_text), instruct_text)
    log.debug("最终响应文本:\n%s", response_text)

    return {
        "response_text": response_text,
        "instruct_text": instruct_text,
        "has_voice": tts.has_reference,
    }


@router.post("/chat/audio")
async def chat_audio(body: dict):
    """
    根据文字生成 TTS 音频流（独立请求，不影响文字回复速度）。
    body: {text, instruct_text}
    """
    text = body.get("text", "")
    instruct_text = body.get("instruct_text", "用平静自然的语气说话。")

    if not text:
        raise HTTPException(status_code=400, detail="Text is required")

    log.info("收到音频合成请求, 文本长度=%d, instruct=%s", len(text), instruct_text)

    tts = _get_tts()
    tts_config = TTSConfig(instruct_text=instruct_text)

    async def audio_stream():
        try:
            async for chunk in tts.speak(text, tts_config):
                yield chunk
            log.debug("TTS 音频流完成")
        except Exception as e:
            log.error("TTS 音频流失败: %s\n%s", e, traceback.format_exc())
            yield b""

    return StreamingResponse(audio_stream(), media_type="audio/wav")


# ─── 灵魂管理路由 ──────────────────────────────────────

@router.get("/soul")
async def get_soul():
    profile = _soul_loader.load()
    log.info("获取 Soul 配置, name=%s, dimensions=%d", profile.name, len(profile.dimensions))
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
    log.info("获取场景信息, scene=%s, len=%d", scene_key, len(current))
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

    log.info("更新场景, 新内容长度=%d", len(content))
    settings = Settings.get()
    settings.update_circumstances(content)
    _get_agent_loop().update_circumstances(content)
    log.info("场景更新完成")
    return {"status": "ok"}


def _get_current_scene_key() -> str:
    """根据当前 circumstances 内容反向查找场景 key"""
    current = Settings.get().circumstances
    for key, val in SCENES.items():
        if val["prompt"].strip() == current.strip():
            return key
    return "custom" if current else ""


# ─── 行为规则卡（必须在 /soul/{dimension} 之前）───────────

@router.get("/soul/skill")
async def get_skill():
    """返回行为规则卡（skill card）。"""
    log.info("获取行为规则卡")
    skill = _soul_loader.load_skill()
    if skill is None:
        return {"skill_card": None}
    log.info("行为规则卡返回, has_content=%s", skill.has_content)
    return {"skill_card": skill.to_dict()}


@router.get("/soul/{dimension}")
async def get_dimension(dimension: str):
    log.info("获取 Soul 维度, dimension=%s", dimension)
    content = _soul_loader.load_dimension(dimension)
    log.info("Soul 维度返回, dimension=%s, len=%d", dimension, len(content))
    return {"dimension": dimension, "content": content}


@router.put("/soul/{dimension}")
async def update_dimension(dimension: str, body: dict):
    content = body.get("content", "")
    log.info("更新 Soul 维度, dimension=%s, 新内容长度=%d", dimension, len(content))
    _soul_loader.save_dimension(dimension, content)
    _get_agent_loop().invalidate_soul_cache()
    log.info("Soul 维度更新完成, dimension=%s", dimension)
    return {"status": "ok"}


# ─── 灵魂档案蒸馏 ───────────────────────────────────────

@router.post("/soul/distill")
async def distill_soul(file: UploadFile = File(...), chat_name: str = Form("")):
    """
    上传 .txt 聊天记录文件，LLM 分析后智能合并到灵魂档案 + 提取行为规则。
    返回变化的维度列表、更新后的完整档案和行为规则卡。

    chat_name: 目标人物在聊天记录中显示的名字（如微信导出中可能是"我"）
    """
    if _distiller is None:
        raise HTTPException(status_code=503, detail="蒸馏服务未初始化")

    log.info("收到蒸馏请求, filename=%s", file.filename)

    # 只接受 .txt 文件
    if file.filename and not file.filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="只支持 .txt 格式的聊天记录文件")

    try:
        raw_bytes = await file.read()
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码不支持，请上传 UTF-8 编码的文件")

    log.info("原始文件大小: %d bytes, %d chars", len(raw_bytes), len(raw_text))

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="聊天记录为空")

    try:
        result = await _distiller.distill(raw_text, chat_name=chat_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("蒸馏失败: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"蒸馏失败: {str(e)}")

    # 蒸馏后刷新 SoulContextModule 缓存
    _get_agent_loop().invalidate_soul_cache()

    log.info("蒸馏完成, changes=%s, has_skill=%s",
             result.changes, bool(result.skill_card and result.skill_card.has_content))

    response = {
        "changes": result.changes,
        "profile": result.profile,
        "summary": result.summary,
    }
    if result.skill_card:
        response["skill_card"] = result.skill_card.to_dict()
    return response


# ─── 配置路由 ──────────────────────────────────────────

@router.get("/settings")
async def get_settings():
    settings = Settings.get()
    log.info("获取设置, log_level=%s, llm_configured=%s", settings.log_level, bool(settings.llm.api_key))
    return {
        "llm": {
            "base_url": settings.llm.base_url,
            "model": settings.llm.model,
            "api_key": "***" if settings.llm.api_key else "",
        },
        "log_level": settings.log_level,
    }


@router.put("/settings")
async def update_settings(body: dict):
    log.info("更新设置, keys=%s", list(body.keys()))
    settings = Settings.get()
    if "llm" in body:
        settings.update_llm(**body["llm"])
        log.info("LLM 设置已更新")
    if "log_level" in body:
        level = body["log_level"]
        if level not in ("debug", "error"):
            raise HTTPException(status_code=400, detail="log_level 必须为 'debug' 或 'error'")
        log.info("日志等级切换: %s → %s", settings.log_level, level)
        settings.update_log_level(level)
    log.info("设置更新完成")
    return {"status": "ok"}


@router.post("/settings/voice/upload")
async def upload_voice_sample(audio: UploadFile = File(...)):
    """
    上传参考音频 → 保存为本地声音克隆参考文件。
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="音频数据为空")

    log.info("收到声音档案上传, 大小: %d bytes", len(audio_bytes))
    try:
        _get_tts().save_reference_audio(audio_bytes)
        log.info("声音档案保存成功, path=%s", _get_tts()._ref_audio_path)
    except Exception as e:
        log.error("声音档案保存失败: %s", e)
        raise HTTPException(status_code=500, detail=f"音频保存失败: {str(e)}")

    return {"status": "ok"}


@router.get("/settings/voice/status")
async def get_voice_status():
    """返回声音档案状态"""
    has_ref = _get_tts().has_reference
    log.info("获取声音档案状态, has_reference=%s", has_ref)
    return {"has_reference": has_ref}


@router.post("/settings/test-llm")
async def test_llm_connection():
    settings = Settings.get()
    log.info("测试 LLM 连接, base_url=%s, model=%s", settings.llm.base_url, settings.llm.model)
    ok = await LLMManager.test_connection(settings.llm)
    log.info("LLM 连接测试结果: %s", "成功" if ok else "失败")
    return {"connected": ok}
