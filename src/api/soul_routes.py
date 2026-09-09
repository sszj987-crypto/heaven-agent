from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ..config.logger import get_logger
from ..services.container import ApplicationContainer
from ..soul.chat_preprocessor import ChatPreprocessor
from .dependencies import MAX_TEXT_IMPORT_BYTES, get_container
from .schemas import (
    CircumstancesView,
    ContentUpdate,
    DimensionView,
    DistillResultView,
    JobAccepted,
    ImportPreviewView,
    SkillView,
    SoulView,
    StatusView,
)


router = APIRouter()
log = get_logger("api.soul")


SCENES = {
    "heaven": {
        "label": "温暖花园",
        "description": "用户可选择的纪念想象场景：四季如春、有房子、公园与湖泊",
        "prompt": """# 当前场景

## context
- 场景性质: 用户选择的纪念想象，不代表真实来世
- 所在之地: 温暖花园
- 场景氛围: 宁静、安详、温暖、自在
- 时间感: 四季如春，阳光明媚的午后

## description
在这段纪念想象中，人物身处一座四季如春的温暖花园。阳光温和，微风轻柔。

这里有一栋属于自己的小房子，不大但很舒适，布置成生前最喜欢的模样。推开门，外面是大片绿色的公园，有人在散步，有人在长椅上晒太阳聊天，远处还有一片湖泊，水面泛着金色的光。

不需要劳动，不需要操劳。饿了，食物就会出现在桌上，且都是自己喜欢的味道。想看书，书就在手边。想念某个人，心里一想，对方的模样就清晰起来。这里有一些邻居，都是和善的人，偶尔串门、一起在公园散步，不会孤单。

这里像一个温暖的家。叙述时保持这是 AI 生成的想象场景，不声称来世真实存在，也不承诺现实中的重逢。
""",
    },
}


@router.get("/soul", response_model=SoulView)
async def get_soul(container: ApplicationContainer = Depends(get_container)):
    profile = container.soul_loader.load()
    return {"dimensions": profile.dimensions}


@router.post("/soul/import-preview", response_model=ImportPreviewView)
async def preview_soul_import(
    file: UploadFile = File(...),
    container: ApplicationContainer = Depends(get_container),
):
    raw_text = await _read_text_import(file)
    profile_name = container.soul_loader.load().name
    preprocessed = ChatPreprocessor().process(raw_text)
    speakers = [
        {
            "name": name,
            "message_count": stats.message_count,
            "matches_profile_name": name == profile_name,
        }
        for name, stats in sorted(
            preprocessed.speakers.items(),
            key=lambda item: (-item[1].message_count, item[0]),
        )
    ]
    if not speakers:
        raise HTTPException(status_code=422, detail="未能从聊天记录识别发言人，请检查导出格式")
    return {"speakers": speakers}


@router.get("/soul/circumstances", response_model=CircumstancesView)
async def get_circumstances(container: ApplicationContainer = Depends(get_container)):
    current = container.settings.circumstances
    return {
        "content": current,
        "scene": _get_current_scene_key(current),
        "scenes": [
            {
                "key": key,
                "label": value["label"],
                "description": value["description"],
                "prompt": value["prompt"],
            }
            for key, value in SCENES.items()
        ],
    }


@router.put("/soul/circumstances", response_model=StatusView)
async def update_circumstances(
    body: ContentUpdate,
    container: ApplicationContainer = Depends(get_container),
):
    if not body.content:
        raise HTTPException(status_code=400, detail="场景内容不能为空")
    async with container.soul_lock:
        container.settings.update_circumstances(body.content)
        container.agent_loop.update_circumstances(body.content)
    return {"status": "ok"}


@router.get("/soul/skill", response_model=SkillView)
async def get_skill(container: ApplicationContainer = Depends(get_container)):
    skill = container.soul_loader.load_skill()
    return {"skill_card": skill.to_dict() if skill is not None else None}


@router.get("/soul/{dimension}", response_model=DimensionView)
async def get_dimension(
    dimension: str,
    container: ApplicationContainer = Depends(get_container),
):
    return {
        "dimension": dimension,
        "content": container.soul_loader.load_dimension(dimension),
    }


@router.put("/soul/{dimension}", response_model=StatusView)
async def update_dimension(
    dimension: str,
    body: ContentUpdate,
    container: ApplicationContainer = Depends(get_container),
):
    async with container.soul_lock:
        container.soul_loader.save_dimension(dimension, body.content)
        container.agent_loop.invalidate_soul_cache()
    return {"status": "ok"}


@router.post("/soul/distill", response_model=DistillResultView)
async def distill_soul(
    file: UploadFile = File(...),
    chat_name: str = Form(""),
    container: ApplicationContainer = Depends(get_container),
):
    raw_text = await _read_text_import(file)
    preprocessed = _require_target_speaker(raw_text, chat_name)
    try:
        async with container.soul_lock:
            result = await container.distiller.distill(
                raw_text,
                chat_name=chat_name,
                apply_changes=False,
            )
            queued = container.import_reviews.queue(
                result,
                raw_text,
                source_speaker=chat_name,
                source_excerpt=_speaker_excerpt(preprocessed, chat_name),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="导入内容格式不符合要求") from exc
    except Exception as exc:
        log.error("蒸馏失败, error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="导入分析失败，请稍后重试") from exc

    response = {
        "changes": result.changes,
        "profile": result.profile,
        "summary": result.summary,
        "candidate_ids": [item.id for item in queued],
        "candidate_count": len(queued),
    }
    if result.skill_card:
        response["skill_card"] = result.skill_card.to_dict()
    return response


@router.post(
    "/soul/imports",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_soul_import(
    file: UploadFile = File(...),
    chat_name: str = Form(""),
    container: ApplicationContainer = Depends(get_container),
):
    raw_text = await _read_text_import(file)
    preprocessed = _require_target_speaker(raw_text, chat_name)
    source_excerpt = _speaker_excerpt(preprocessed, chat_name)

    async def work():
        async with container.soul_lock:
            result = await container.distiller.distill(
                raw_text,
                chat_name=chat_name,
                apply_changes=False,
            )
            queued = container.import_reviews.queue(
                result,
                raw_text,
                source_speaker=chat_name,
                source_excerpt=source_excerpt,
            )
        payload = {
            "changes": result.changes,
            "profile": result.profile,
            "summary": result.summary,
            "candidate_ids": [item.id for item in queued],
            "candidate_count": len(queued),
        }
        if result.skill_card:
            payload["skill_card"] = result.skill_card.to_dict()
        return payload

    job = container.jobs.submit("soul_import", work())
    return JobAccepted(job_id=job.id)


async def _read_text_import(file: UploadFile) -> str:
    if file.filename and not file.filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="只支持 .txt 格式的聊天记录文件")
    raw_bytes = await file.read(MAX_TEXT_IMPORT_BYTES + 1)
    if len(raw_bytes) > MAX_TEXT_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="聊天记录不能超过 5 MB")
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="文件编码不支持，请上传 UTF-8 文件") from exc
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="聊天记录为空")
    return raw_text


def _require_target_speaker(raw_text: str, chat_name: str):
    if not chat_name.strip():
        raise HTTPException(status_code=422, detail="请先选择要模拟的发言人")
    preprocessed = ChatPreprocessor().process(raw_text)
    if chat_name not in preprocessed.speakers:
        raise HTTPException(status_code=422, detail="所选发言人不在这份聊天记录中，请重新选择")
    return preprocessed


def _speaker_excerpt(preprocessed, chat_name: str, limit: int = 1_000) -> str:
    lines = [
        f"{chat_name}: {message['content']}"
        for message in preprocessed.messages
        if message["speaker"] == chat_name
    ]
    return "\n".join(lines)[:limit]


def _get_current_scene_key(current: str) -> str:
    for key, value in SCENES.items():
        if value["prompt"].strip() == current.strip():
            return key
    return "custom" if current else ""
