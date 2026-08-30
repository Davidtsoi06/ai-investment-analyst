# -*- coding: utf-8 -*-
"""FastAPI 入口：健康检查 + 生命周期初始化"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

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


@app.get("/api/health")
def health():
    return {"status": "ok", "version": settings.version, "db": str(settings.db_path)}
