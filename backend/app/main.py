# -*- coding: utf-8 -*-
"""FastAPI 入口：健康检查 + 行情接口 + 生命周期初始化"""

from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models.database import init_db
from .services.logger import get_app_logger
from .services.scheduler import start_scheduler, stop_scheduler
from .services.portfolio_sync import sync_now, portfolio_status, register_hourly_sync
from .data_sources.market.data_fusion import data_fusion

logger = get_app_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    start_scheduler()
    register_hourly_sync()
    logger.info("数据库初始化完成: %s", settings.db_path)
    yield
    stop_scheduler()
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
    require_token(x_backend_token)
    return {"status": "ok", "version": settings.version, "db": str(settings.db_path)}


@app.get("/api/market/quote")
def market_quote(
    symbol: str = Query(..., description="股票代码，如 600519 / 00700"),
    market: str = Query("A股", description="A股/港股"),
    x_backend_token: str = Header(default=""),
):
    require_token(x_backend_token)
    q = data_fusion.get_quote(symbol.strip(), market)
    if q is None:
        raise HTTPException(status_code=404, detail="行情获取失败（数据源不可用）")
    return asdict(q)


@app.get("/api/market/kline")
def market_kline(
    symbol: str = Query(..., description="股票代码，如 600519 / 00700"),
    market: str = Query("A股"),
    days: int = Query(120, ge=10, le=500),
    x_backend_token: str = Header(default=""),
):
    require_token(x_backend_token)
    bars = data_fusion.get_kline(symbol.strip(), market, days)
    if bars is None:
        raise HTTPException(status_code=404, detail="K线获取失败（数据源不可用）")
    return {"symbol": symbol.strip(), "market": market, "bars": [asdict(b) for b in bars]}


# ---------------- 用户画像与系统设置（S7） ----------------

from typing import Any  # noqa: E402

from pydantic import BaseModel  # noqa: E402

from .services.profile_service import get_profile, save_profile  # noqa: E402
from .services.settings_service import (  # noqa: E402
    get_all_settings,
    save_settings,
    save_ai_key,
    ai_key_configured,
)
from .services.llm_client import test_connection  # noqa: E402


class ProfileIn(BaseModel):
    risk_tolerance: str = '稳健型'
    invest_amount: str = '10-50万'
    markets: list[str] = ['A股', '港股']
    holding_period: str = '数天~数周'
    experience: str = '有经验'


class SettingsIn(BaseModel):
    markets: list[str] | None = None
    notifications: dict[str, Any] | None = None
    quiet_hours: dict[str, Any] | None = None


class AiKeyIn(BaseModel):
    api_key: str


@app.get("/api/profile")
def profile_get(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return get_profile()


@app.put("/api/profile")
def profile_put(data: ProfileIn, x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return save_profile(data.model_dump())


@app.get("/api/settings")
def settings_get(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    result = get_all_settings()
    result['ai_configured'] = ai_key_configured()
    return result


@app.put("/api/settings")
def settings_put(data: SettingsIn, x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    body = {k: v for k, v in data.model_dump().items() if v is not None}
    return save_settings(body)


@app.post("/api/settings/ai-key")
def ai_key_save(data: AiKeyIn, x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return save_ai_key(data.api_key)


@app.post("/api/settings/ai-test")
def ai_key_test(data: AiKeyIn | None = None, x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    key = data.api_key if data else None
    return test_connection(key)


@app.get("/api/portfolio/status")
def portfolio_status_api(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return portfolio_status()


@app.post("/api/portfolio/sync")
def portfolio_sync_api(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return sync_now()


@app.get("/api/portfolio/overview")
def portfolio_overview_api(x_backend_token: str = Header(default="")):
    """持仓总览：本地 holdings 明细 + 理财软件快照（账户/净值）"""
    require_token(x_backend_token)
    conn = None
    try:
        from .models.database import get_connection
        conn = get_connection()
        holdings = [
            dict(r)
            for r in conn.execute(
                "SELECT symbol, name, market, currency, quantity, cost_price, current_price, source, sync_at FROM holdings ORDER BY source, market"
            )
        ]
    finally:
        if conn:
            conn.close()
    from .models.database import get_connection as _gc
    _conn = _gc()
    try:
        row = _conn.execute(
            "SELECT value FROM system_settings WHERE key = 'portfolio_snapshot_v1'"
        ).fetchone()
    finally:
        _conn.close()
    import json as _json
    snapshot = _json.loads(row['value']) if row else None
    return {
        "holdings": holdings,
        "snapshot": snapshot,
        "status": portfolio_status(),
    }
