from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from ..config.logger import get_logger
from ..memory.candidates import CandidateNotFound, CandidateStateError
from ..services.container import ApplicationContainer
from .dependencies import get_container
from .schemas import (
    CandidateResolution,
    MemoryCandidateView,
    MemoryEntryView,
    MemoryStatsView,
    StatusView,
)


router = APIRouter()
log = get_logger("api.memory")


@router.get("/memory/stats", response_model=MemoryStatsView)
async def get_memory_stats(container: ApplicationContainer = Depends(get_container)):
    return _require_memory_store(container).stats()


@router.get("/memory/candidates", response_model=list[MemoryCandidateView])
async def get_memory_candidates(
    status: str = "pending",
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return [
            MemoryCandidateView(**asdict(item))
            for item in container.candidate_service.list(status)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/memory/candidates/{candidate_id}/approve",
    response_model=MemoryCandidateView,
)
async def approve_memory_candidate(
    candidate_id: str,
    body: CandidateResolution,
    container: ApplicationContainer = Depends(get_container),
):
    try:
        async with container.soul_lock:
            item = container.candidate_service.approve(candidate_id, body.content)
        return MemoryCandidateView(**asdict(item))
    except CandidateNotFound as exc:
        raise HTTPException(status_code=404, detail="候选事实不存在") from exc
    except CandidateStateError as exc:
        raise HTTPException(status_code=409, detail="候选事实已经处理") from exc


@router.post(
    "/memory/candidates/{candidate_id}/reject",
    response_model=MemoryCandidateView,
)
async def reject_memory_candidate(
    candidate_id: str,
    container: ApplicationContainer = Depends(get_container),
):
    try:
        async with container.soul_lock:
            item = container.candidate_service.reject(candidate_id)
        return MemoryCandidateView(**asdict(item))
    except CandidateNotFound as exc:
        raise HTTPException(status_code=404, detail="候选事实不存在") from exc
    except CandidateStateError as exc:
        raise HTTPException(status_code=409, detail="候选事实已经处理") from exc


@router.get("/memory/{dimension}", response_model=list[MemoryEntryView])
async def get_memory_by_dimension(
    dimension: str,
    container: ApplicationContainer = Depends(get_container),
):
    return _require_memory_store(container).get_by_dimension(dimension)


@router.delete("/memory/{memory_id}", response_model=StatusView)
async def delete_memory(
    memory_id: str,
    container: ApplicationContainer = Depends(get_container),
):
    async with container.soul_lock:
        if not _require_memory_store(container).delete(memory_id):
            raise HTTPException(status_code=404, detail="记忆不存在或删除失败")
    return {"status": "ok"}


def _require_memory_store(container: ApplicationContainer):
    if container.memory_store is None:
        raise HTTPException(status_code=503, detail="记忆索引当前不可用")
    return container.memory_store
