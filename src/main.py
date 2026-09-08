import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from src.config.settings import Settings
from src.config.logger import init_logger
from src.api.routes import router
from src.api.schemas import ErrorBody
from src.services.container import ApplicationContainer
from src.voice.minimax import MiniMaxError


def create_app(container_factory=ApplicationContainer.create) -> FastAPI:
    settings = Settings.init(ROOT / "config")
    init_logger(settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        container = container_factory(ROOT, settings)
        application.state.container = container
        try:
            yield
        finally:
            await container.close()

    application = FastAPI(
        title="Heaven Agent",
        version="0.2.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - started) * 1000
        response.headers["x-request-id"] = request_id
        response.headers["x-process-time-ms"] = f"{elapsed_ms:.1f}"
        return response

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:16])
        body = ErrorBody(
            code=f"http_{exc.status_code}",
            message=str(exc.detail),
            retryable=exc.status_code >= 500,
            request_id=request_id,
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:16])
        first = exc.errors()[0] if exc.errors() else {"msg": "请求参数无效"}
        body = ErrorBody(
            code="validation_error",
            message=str(first.get("msg", "请求参数无效")),
            retryable=False,
            request_id=request_id,
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    @application.exception_handler(MiniMaxError)
    async def minimax_error(request: Request, exc: MiniMaxError):
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:16])
        body = ErrorBody(
            code="minimax_error",
            message=str(exc),
            retryable=exc.retryable,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=502,
            content=body.model_dump(),
            headers={"x-request-id": request_id},
        )

    @application.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:16])
        # Do not expose or log exception text: provider errors can contain private input.
        body = ErrorBody(
            code="internal_error",
            message="服务器内部错误",
            retryable=True,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=500,
            content=body.model_dump(),
            headers={"x-request-id": request_id},
        )

    application.include_router(router)

    @application.get("/")
    async def root():
        return {"name": "Heaven Agent", "version": "0.2.0", "message": "AI 人物模拟与纪念对话"}

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8326, reload=True)
