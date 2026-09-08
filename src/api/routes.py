"""Application router assembled from focused capability routers."""

from fastapi import APIRouter

from .chat_routes import router as chat_router
from .memory_routes import router as memory_router
from .settings_routes import router as settings_router
from .soul_routes import router as soul_router
from .system_routes import router as system_router


router = APIRouter()
router.include_router(system_router)
router.include_router(chat_router)
router.include_router(soul_router)
router.include_router(memory_router)
router.include_router(settings_router)
