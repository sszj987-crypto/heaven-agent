import sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.config.settings import Settings
from src.api.routes import router, init_services

# 初始化配置
settings = Settings.init(ROOT / "config")

# 初始化日志
from src.config.logger import init_logger
init_logger(settings.log_level)

app = FastAPI(title="VoiceFromHeaven", version="0.1.0")

# 启动时初始化全局服务
@app.on_event("startup")
async def startup():
    init_services()

# CORS 允许前端跨域，来源由 config/app.json 中的 frontend_origin 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {"name": "VoiceFromHeaven", "version": "0.1.0", "message": "让思念有回响"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8326, reload=True)
