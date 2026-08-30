# -*- coding: utf-8 -*-
"""FastAPI 入口：健康检查 + 生命周期初始化 + 令牌校验"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models.database import init_db
from .services.logger import get_app_logger

logger = get_app_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info("数据库初始化完成: %s", settings.db_path)
    yield
    logger.info("应用退出")


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

# 允许本机前端调试访问（生产环境由 Electron 主进程代理，无跨域问题）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(x_backend_token: str = Header(default="")) -> None:
    """令牌校验：主进程注入令牌后，所有请求必须携带"""
    if settings.backend_token and x_backend_token != settings.backend_token:
        raise HTTPException(status_code=401, detail="invalid backend token")


@app.get("/api/health")
def health(_: None = None, x_backend_token: str = Header(default="")):
    """健康检查：令牌模式启动时需携带 X-Backend-Token"""
    require_token(x_backend_token)
    return {"status": "ok", "version": settings.version, "db": str(settings.db_path)}
