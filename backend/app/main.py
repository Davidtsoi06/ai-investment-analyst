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
from .services.notification import send_notification, list_notifications
from .services.settings_service import get_setting, set_setting
from .services.trading_calendar import is_trading_day
from .agents.news_agent import collect_and_analyze, build_premarket_content
from .data_sources.market.data_fusion import data_fusion

logger = get_app_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    start_scheduler()
    register_hourly_sync()
    register_news_jobs()
    register_recommend_jobs()
    start_tracking_polling()
    register_summary_jobs()
    catchup_summaries()
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


# ---------------- 资讯与通知（S8） ----------------

from datetime import date, datetime as _dt  # noqa: E402

from .models.database import get_connection  # noqa: E402

PREMARKET_KEY = 'premarket_today'


def _run_premarket() -> dict:
    """抓取整合资讯并生成盘前内容（供 08:00 定时与手动触发）"""
    result = collect_and_analyze()
    if not result.get('ok'):
        return result
    content = build_premarket_content(result['items'])
    set_setting(PREMARKET_KEY, {
        'date': date.today().isoformat(),
        'content': content,
        'fetched': result.get('fetched'),
        'saved': result.get('saved'),
        'created_at': _dt.now().strftime('%Y-%m-%d %H:%M:%S'),
        'pushed': False,
    })
    result['content'] = content
    return result


def _push_premarket() -> dict:
    """推送今日盘前资讯（09:00 定时；当日不重复）"""
    today = date.today().isoformat()
    pm = get_setting(PREMARKET_KEY) or {}
    if pm.get('date') != today:
        _run_premarket()
        pm = get_setting(PREMARKET_KEY) or {}
    if pm.get('pushed'):
        return {'sent': False, 'reason': '今日已推送'}
    content = pm.get('content', '今日暂无资讯')
    r = send_notification('premarket', '📰 盘前资讯速递', content, level='提示', force=True)
    if r.get('sent'):
        pm['pushed'] = True
        set_setting(PREMARKET_KEY, pm)
    return {'sent': r.get('sent'), 'reason': r.get('reason', '')}


def register_news_jobs() -> None:
    """注册盘前资讯定时任务（仅交易日）"""
    from .services.scheduler import add_cron_job

    def _collect_job() -> None:
        if not is_trading_day('A股'):
            return
        try:
            _run_premarket()
        except Exception as e:  # noqa: BLE001
            logger.error('盘前抓取失败: %s', e)

    def _push_job() -> None:
        if not is_trading_day('A股'):
            return
        try:
            _push_premarket()
        except Exception as e:  # noqa: BLE001
            logger.error('盘前推送失败: %s', e)

    add_cron_job(_collect_job, hour=8, minute=0, job_id='news_premarket_collect')
    add_cron_job(_push_job, hour=9, minute=0, job_id='news_premarket_push')
    logger.info('盘前资讯定时任务已注册（08:00 抓取 / 09:00 推送，仅交易日）')


@app.get("/api/news/latest")
def news_latest(limit: int = 30, x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, url, source, market, summary, level, published_at, created_at "
            "FROM news_cache ORDER BY id DESC LIMIT ?",
            (min(limit, 100),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/news/premarket/run")
def news_premarket_run(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return _run_premarket()


@app.get("/api/news/premarket/today")
def news_premarket_today(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return get_setting(PREMARKET_KEY) or {'date': None, 'content': '今日尚无盘前资讯'}


@app.post("/api/news/premarket/push")
def news_premarket_push(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return _push_premarket()


@app.get("/api/notifications")
def notifications_get(limit: int = 30, x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return list_notifications(limit)


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

# ---------------- 自选股看板（S9） ----------------

from .services.watchlist_service import (  # noqa: E402
    add_watchlist as _wl_add,
    delete_watchlist as _wl_delete,
    list_groups as _wl_groups,
    list_watchlist as _wl_list,
    update_watchlist as _wl_update,
)


class WatchlistIn(BaseModel):
    symbol: str
    name: str = ''
    market: str = 'A股'
    group_name: str = '默认'


class WatchlistUpdateIn(BaseModel):
    name: str | None = None
    group_name: str | None = None
    sort_order: int | None = None


@app.get("/api/watchlist")
def watchlist_get(x_backend_token: str = Header(default="")):
    """全部自选股（按 group_name / sort_order 排序，含各组）"""
    require_token(x_backend_token)
    return _wl_list()


@app.get("/api/watchlist/groups")
def watchlist_groups(x_backend_token: str = Header(default="")):
    """自选股分组名列表（前端 tab 用）"""
    require_token(x_backend_token)
    return _wl_groups()


@app.post("/api/watchlist")
def watchlist_post(data: WatchlistIn, x_backend_token: str = Header(default="")):
    """添加自选股（symbol 重复拒绝 409；name 为空自动查行情补全）"""
    require_token(x_backend_token)
    try:
        return _wl_add(data.symbol, data.name, data.market, data.group_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.put("/api/watchlist/{item_id}")
def watchlist_put(item_id: int, data: WatchlistUpdateIn, x_backend_token: str = Header(default="")):
    """更新自选股（name / group_name / sort_order 可部分更新）"""
    require_token(x_backend_token)
    try:
        return _wl_update(item_id, name=data.name, group_name=data.group_name, sort_order=data.sort_order)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/watchlist/{item_id}")
def watchlist_delete(item_id: int, x_backend_token: str = Header(default="")):
    """删除自选股"""
    require_token(x_backend_token)
    try:
        _wl_delete(item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "id": item_id}


@app.get("/api/news/related")
def news_related(
    keyword: str = Query(..., min_length=1, description="查询关键词（标题/摘要模糊匹配）"),
    limit: int = Query(10, ge=1, le=50),
    x_backend_token: str = Header(default=""),
):
    """关联资讯：按关键词查 news_cache（title / summary LIKE）"""
    require_token(x_backend_token)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, summary, level, published_at FROM news_cache "
            "WHERE title LIKE ? OR summary LIKE ? ORDER BY id DESC LIMIT ?",
            (f'%{keyword}%', f'%{keyword}%', min(limit, 50)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------- 推荐模块（S10） ----------------

from .agents.recommend_agent import generate_recommendations  # noqa: E402
from .services.backtest_service import (  # noqa: E402
    evaluate_pending,
    get_backtest_report,
    recommendation_history,
)


@app.get("/api/recommend/today")
def recommend_today(x_backend_token: str = Header(default="")):
    """今日推荐（未生成时自动触发生成；已生成返回缓存）"""
    require_token(x_backend_token)
    return generate_recommendations(force=False)


@app.post("/api/recommend/run")
def recommend_run(x_backend_token: str = Header(default="")):
    """手动触发重新生成当日推荐"""
    require_token(x_backend_token)
    return generate_recommendations(force=True)


@app.get("/api/recommend/history")
def recommend_history_api(limit: int = Query(50, ge=1, le=200), x_backend_token: str = Header(default="")):
    """推荐历史（含回测结果），按日期倒序"""
    require_token(x_backend_token)
    return recommendation_history(limit)


@app.get("/api/recommend/backtest")
def recommend_backtest(x_backend_token: str = Header(default="")):
    """回测报告：胜率 / 平均收益 / 分类型 / 分月 / 明细（自动先结算未评估推荐）"""
    require_token(x_backend_token)
    return get_backtest_report()


@app.post("/api/recommend/backtest/evaluate")
def recommend_backtest_evaluate(x_backend_token: str = Header(default="")):
    """手动结算未评估推荐"""
    require_token(x_backend_token)
    return evaluate_pending()


# ---- 契约别名（/api/recommendations/*，与 /api/recommend/* 等价） ----

@app.post("/api/recommendations/generate")
def recommendations_generate(x_backend_token: str = Header(default="")):
    """生成今日推荐（已生成返回 existing:true，不重复生成）"""
    require_token(x_backend_token)
    result = generate_recommendations(force=False)
    result['existing'] = result.get('cached', False)
    return result


@app.get("/api/recommendations/today")
def recommendations_today(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return generate_recommendations(force=False)


@app.get("/api/recommendations/history")
def recommendations_history(limit: int = Query(50, ge=1, le=200), x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return recommendation_history(limit)


@app.get("/api/recommendations/performance")
def recommendations_performance(x_backend_token: str = Header(default="")):
    require_token(x_backend_token)
    return get_backtest_report()


def register_recommend_jobs() -> None:
    """注册每日 09:15 推荐生成定时任务（仅交易日，重复执行自动覆盖当日）"""
    from .services.scheduler import add_cron_job

    def _recommend_job() -> None:
        if not is_trading_day('A股'):
            return
        try:
            generate_recommendations(force=True)
        except Exception as e:  # noqa: BLE001
            logger.error('定时推荐生成失败: %s', e)

    add_cron_job(_recommend_job, hour=9, minute=15, job_id='recommend_daily')
    logger.info('推荐定时任务已注册（09:15 每日，仅交易日）')


# ---------------- 实时追踪（S11） ----------------

from .services.tracking_service import (  # noqa: E402
    add_tracking as _tr_add,
    delete_tracking as _tr_delete,
    list_events as _tr_events,
    list_tracking as _tr_list,
    update_tracking as _tr_update,
    TrackingDuplicateError,
    TrackingLimitError,
)
from .agents.tracking_agent import run_check as _tr_run_check  # noqa: E402
from .services.tracking_scheduler import (  # noqa: E402
    ensure_tracking_polling,
    start_tracking_polling,
    stop_tracking_polling,
)


class TrackingIn(BaseModel):
    symbol: str
    name: str = ''
    market: str = 'A股'
    price_change_pct: float | None = None
    volume_ratio: float | None = None
    big_order_amount: float | None = None
    tech_signals: int | None = None
    ai_judge: int | None = None


class TrackingUpdateIn(BaseModel):
    name: str | None = None
    price_change_pct: float | None = None
    volume_ratio: float | None = None
    big_order_amount: float | None = None
    tech_signals: int | None = None
    ai_judge: int | None = None
    active: int | None = None


def _tracking_error(e: Exception) -> HTTPException:
    """错误映射：重复 409 / 上限·市场·参数 400 / 不存在 404"""
    if isinstance(e, TrackingDuplicateError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, TrackingLimitError):
        return HTTPException(status_code=400, detail=str(e))
    msg = str(e)
    if '不存在' in msg:
        return HTTPException(status_code=404, detail=msg)
    return HTTPException(status_code=400, detail=msg)


@app.get("/api/tracking")
def tracking_list(x_backend_token: str = Header(default="")):
    """全部追踪（含今日触发次数与今日事件数）"""
    require_token(x_backend_token)
    return _tr_list()


@app.post("/api/tracking")
def tracking_add(data: TrackingIn, x_backend_token: str = Header(default="")):
    """添加追踪：总量≤10 / market 开启校验 / 重复 409 / name 自动补全"""
    require_token(x_backend_token)
    try:
        row = _tr_add(
            data.symbol, data.name, data.market,
            price_change_pct=data.price_change_pct,
            volume_ratio=data.volume_ratio,
            big_order_amount=data.big_order_amount,
            tech_signals=data.tech_signals,
            ai_judge=data.ai_judge,
        )
    except ValueError as e:
        raise _tracking_error(e)
    ensure_tracking_polling()
    return row


@app.put("/api/tracking/{item_id}")
def tracking_update(item_id: int, data: TrackingUpdateIn, x_backend_token: str = Header(default="")):
    """更新追踪条件或 active（暂停=0 / 启用=1）"""
    require_token(x_backend_token)
    try:
        row = _tr_update(
            item_id,
            name=data.name,
            price_change_pct=data.price_change_pct,
            volume_ratio=data.volume_ratio,
            big_order_amount=data.big_order_amount,
            tech_signals=data.tech_signals,
            ai_judge=data.ai_judge,
            active=data.active,
        )
    except ValueError as e:
        raise _tracking_error(e)
    if data.active is not None:
        ensure_tracking_polling()
    return row


@app.delete("/api/tracking/{item_id}")
def tracking_delete(item_id: int, x_backend_token: str = Header(default="")):
    """删除追踪（连同事件记录）"""
    require_token(x_backend_token)
    try:
        _tr_delete(item_id)
    except ValueError as e:
        raise _tracking_error(e)
    if not _tr_list():
        stop_tracking_polling()
    return {"ok": True, "id": item_id}


@app.get("/api/tracking/events")
def tracking_events(limit: int = Query(30, ge=1, le=200), x_backend_token: str = Header(default="")):
    """异动事件历史（时间倒序）"""
    require_token(x_backend_token)
    return _tr_events(limit)


@app.post("/api/tracking/check")
def tracking_check(x_backend_token: str = Header(default="")):
    """手动触发一次全量异动检测（真实行情，返回检测结果）"""
    require_token(x_backend_token)
    return _tr_run_check()


# ---------------- 盘后总结（S12） ----------------

from .agents.summary_agent import (  # noqa: E402
    catchup_summaries,
    generate_combined_report as _sum_combined,
    generate_market_summary as _sum_generate,
    get_latest_report as _sum_latest,
    get_today_summary as _sum_today,
    list_summaries as _sum_history,
    register_summary_jobs,
)
from .data_sources.market.snapshot_client import collect_snapshot  # noqa: E402


class SummaryRunIn(BaseModel):
    market: str = 'A股'
    force: bool = False


@app.get("/api/summary/today")
def summary_today(
    market: str = Query('A股', description='A股/港股/合并'),
    x_backend_token: str = Header(default=""),
):
    """当日盘后报告（已生成返回；未生成 exists=false，不自动触发 AI 调用）"""
    require_token(x_backend_token)
    report = _sum_today(market)
    if report is None:
        return {'exists': False, 'market': market, 'report': None,
                'reason': '当日报告尚未生成（可调用 POST /api/summary/run 生成）'}
    return {'exists': True, 'market': market, 'report': report}


@app.post("/api/summary/run")
def summary_run(data: SummaryRunIn, x_backend_token: str = Header(default="")):
    """生成盘后总结：market=A股/港股/合并；force=true 强制重新生成"""
    require_token(x_backend_token)
    market = (data.market or 'A股').strip()
    if market == '合并':
        return _sum_combined(force=data.force)
    return _sum_generate(market, force=data.force)


@app.get("/api/summary/history")
def summary_history(limit: int = Query(30, ge=1, le=200), x_backend_token: str = Header(default="")):
    """盘后报告历史（按日期倒序）"""
    require_token(x_backend_token)
    return {'items': _sum_history(limit)}


@app.get("/api/summary/latest")
def summary_latest(x_backend_token: str = Header(default="")):
    """最新报告（优先当日合并日报；无则最近一份）"""
    require_token(x_backend_token)
    report = _sum_latest()
    if report is None:
        return {'exists': False, 'report': None, 'reason': '暂无盘后报告'}
    return {'exists': True, 'report': report}


@app.get("/api/summary/snapshot")
def summary_snapshot(
    market: str = Query('A股', description='A股/港股'),
    x_backend_token: str = Header(default=""),
):
    """实时市场快照（指数/板块/成交额/情绪），供报告页展示与调试"""
    require_token(x_backend_token)
    if market not in ('A股', '港股'):
        raise HTTPException(status_code=400, detail='market 仅支持 A股/港股')
    return collect_snapshot(market)


