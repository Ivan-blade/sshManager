"""sshManager FastAPI 应用组装。

路由注册顺序在前，根路径静态挂载在后 —— 保证 /api、/ws 先被匹配。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .deps import get_manager
from .routes import ai, sessions, sftp, terminal


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await get_manager().shutdown()


app = FastAPI(title="sshManager", version="0.1.0", lifespan=lifespan)

# 开发期放开 CORS，方便前端以任意来源调试
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(terminal.router)
app.include_router(ai.router)
app.include_router(sftp.router)

# 前端静态资源（xterm.js 本地化，离线可用）
if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
