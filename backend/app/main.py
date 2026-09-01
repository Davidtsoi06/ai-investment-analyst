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
    register_review_jobs()
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
    today_reports as _sum_today_all,
)
from .data_sources.market.snapshot_client import collect_snapshot  # noqa: E402


class SummaryRunIn(BaseModel):
    market: str = 'A股'
    force: bool = False


@app.post("/api/summary/generate")
def summary_generate(
    market: str = Query('A股', description='A股/港股'),
    x_backend_token: str = Header(default=""),
):
    """生成单市场盘后总结（契约主入口）：当日同市场已生成返回 existing=true 幂等。
    返回 {ok, existing, market, report, error?}"""
    require_token(x_backend_token)
    result = _sum_generate((market or 'A股').strip(), force=False)
    if not result.get('ok'):
        return {'ok': False, 'existing': False, 'market': market,
                'report': None, 'error': result.get('reason', '生成失败')}
    return {'ok': True, 'existing': bool(result.get('cached')), 'market': market,
            'report': result.get('report'), 'error': None}


@app.get("/api/summary/today")
def summary_today(
    market: str | None = Query(None, description='A股/港股/合并（缺省返回今日全部市场列表）'),
    x_backend_token: str = Header(default=""),
):
    """当日盘后报告：
    - 无 market 参数：今日全部市场报告数组（缺失且交易日自动触发生成，兼容前端契约）
    - 带 market 参数：单市场报告（未生成 exists=false，不自动触发）"""
    require_token(x_backend_token)
    if market:
        report = _sum_today(market)
        if report is None:
            return {'exists': False, 'market': market, 'report': None,
                    'reason': '当日报告尚未生成（可调用 POST /api/summary/generate 生成）'}
        return {'exists': True, 'market': market, 'report': report}
    return _sum_today_all(auto_generate=True)


@app.post("/api/summary/run")
def summary_run(data: SummaryRunIn, x_backend_token: str = Header(default="")):
    """生成盘后总结（调试/强制入口）：market=A股/港股/合并；force=true 强制重新生成"""
    require_token(x_backend_token)
    market = (data.market or 'A股').strip()
    if market == '合并':
        return _sum_combined(force=data.force)
    return _sum_generate(market, force=data.force)


@app.post("/api/summary/daily")
def summary_daily(x_backend_token: str = Header(default="")):
    """合并生成全市场日报（契约主入口）：当日 A股+港股 报告拼接 + 通知推送。
    返回 {ok, existing, report, sent, reason?}"""
    require_token(x_backend_token)
    result = _sum_combined(force=False)
    if not result.get('ok'):
        return {'ok': False, 'existing': False, 'report': None,
                'sent': False, 'reason': result.get('reason', '合并日报生成失败')}
    return {'ok': True, 'existing': bool(result.get('cached')),
            'report': result.get('report'), 'sent': True,
            'reason': '已推送应用内通知' if not result.get('cached') else '今日已生成（生成时已推送）'}


@app.get("/api/summary/history")
def summary_history(limit: int = Query(30, ge=1, le=200), x_backend_token: str = Header(default="")):
    """盘后报告历史（按日期倒序，直接返回数组，兼容前端契约）"""
    require_token(x_backend_token)
    return _sum_history(limit)


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


# ---------------- 智能问答与研报解读（S13） ----------------

from .agents.chat_agent import ask as _chat_ask  # noqa: E402
from .agents.chat_agent import list_history as _chat_history  # noqa: E402
from .data_sources.research.eastmoney_research import (  # noqa: E402
    fetch_research as _research_list,
    interpret_research as _research_interpret,
)


class ChatAskIn(BaseModel):
    question: str


class ResearchInterpretIn(BaseModel):
    keyword: str | None = None
    title: str | None = None


@app.post("/api/chat/ask")
def chat_ask(data: ChatAskIn, x_backend_token: str = Header(default="")):
    """智能问答：问题分类 + 上下文（实时行情/指标/画像/持仓/资讯）+ AI 或降级回答，保存对话历史。
    返回 {answer, category, used_data:{quotes,kline_summary,holdings,news}, degraded}"""
    require_token(x_backend_token)
    question = (data.question or '').strip()
    if not question:
        raise HTTPException(status_code=400, detail='question 不能为空')
    try:
        return _chat_ask(question)
    except Exception as e:  # noqa: BLE001
        logger.exception('智能问答失败')
        raise HTTPException(status_code=500, detail=f'问答失败: {e}')


@app.get("/api/chat/history")
def chat_history_api(
    limit: int = Query(30, ge=1, le=100, description='返回条数'),
    x_backend_token: str = Header(default=""),
):
    """对话历史（按时间倒序，含分类/回答/所用数据快照/是否降级）"""
    require_token(x_backend_token)
    return _chat_history(limit)


@app.get("/api/research/list")
def research_list_api(
    keyword: str = Query('', description='关键词（标题/股票名/代码过滤，可空）'),
    limit: int = Query(10, ge=1, le=50, description='返回条数'),
    x_backend_token: str = Header(default=""),
):
    """研报列表（数组）：优先东财研报接口；不可用时降级本地资讯缓存。
    条目含 {title, org, rating, rating_change, target_price, date, stock, url, source}，
    source='eastmoney' 或 'news_cache'（降级时逐条标注，日志记录降级原因）"""
    require_token(x_backend_token)
    try:
        result = _research_list(keyword or None, limit)
        if result.get('note'):
            logger.info('研报列表降级为资讯缓存: %s', result.get('note'))
        return result.get('items') or []
    except Exception as e:  # noqa: BLE001
        logger.exception('研报列表失败')
        raise HTTPException(status_code=500, detail=f'研报列表失败: {e}')


@app.post("/api/research/interpret")
def research_interpret_api(
    data: ResearchInterpretIn,
    x_backend_token: str = Header(default=""),
):
    """研报 AI 解读：{keyword 或 title} → 核心观点（目标价/评级变化/关键假设/风险提示，300 字摘要）
    + 持仓关联分析；无 Key 或失败走降级模板"""
    require_token(x_backend_token)
    try:
        return _research_interpret(title=data.title, keyword=data.keyword)
    except Exception as e:  # noqa: BLE001
        logger.exception('研报解读失败')
        raise HTTPException(status_code=500, detail=f'研报解读失败: {e}')


# ---------------- 风险分析与宏观研判（S14） ----------------

from .services.risk_service import (  # noqa: E402
    compute_risk_overview as _risk_overview,
    list_risk_alerts as _risk_alerts,
    stress_test as _risk_stress_test,
)
from .agents.macro_agent import (  # noqa: E402
    get_macro_overview as _macro_overview,
    refresh_macro as _macro_refresh,
)


class StressTestIn(BaseModel):
    scenario: str


@app.get("/api/risk/overview")
def risk_overview_api(x_backend_token: str = Header(default="")):
    """组合风险总览：集中度 / 最大回撤 / Beta / 夏普 / VaR + 预警（命中预警自动通知，30 分钟冷却）"""
    require_token(x_backend_token)
    return _risk_overview(notify=True)


@app.post("/api/risk/stress-test")
def risk_stress_test_api(data: StressTestIn, x_backend_token: str = Header(default="")):
    """压力测试：scenario = market_down_10 | hk_tech_down_20 | cny_depreciate_5"""
    require_token(x_backend_token)
    try:
        return _risk_stress_test((data.scenario or '').strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/risk/alerts")
def risk_alerts_api(limit: int = Query(20, ge=1, le=100), x_backend_token: str = Header(default="")):
    """最近风险预警通知（notification_log type='risk'）"""
    require_token(x_backend_token)
    return _risk_alerts(limit)


@app.get("/api/macro/overview")
def macro_overview_api(x_backend_token: str = Header(default="")):
    """宏观总览：全球/中国指标列表 + 四色信号（当日已有缓存直接返回）"""
    require_token(x_backend_token)
    return _macro_overview(refresh=False)


@app.get("/api/macro/overview")
def macro_overview_api(x_backend_token: str = Header(default="")):
    """宏观总览：全球/中国指标列表 + 四色信号（当日已有缓存直接返回）"""
    require_token(x_backend_token)
    return _macro_overview(refresh=False)


@app.post("/api/macro/refresh")
def macro_refresh_api(x_backend_token: str = Header(default="")):
    """强制重新采集宏观指标并更新四色信号（幂等）"""
    require_token(x_backend_token)
    return _macro_refresh()


# ---------------- 投资复盘（S15） ----------------

from .agents.review_agent import (  # noqa: E402
    generate_review as _review_generate,
    get_latest_review as _review_latest,
    get_latest_review_of as _review_latest_of,
    list_reviews as _review_history,
)

VALID_REVIEW_PERIODS = ('weekly', 'monthly', 'quarterly')
# 前端别名兼容：week->weekly / month->monthly / quarter->quarterly
PERIOD_ALIAS = {'week': 'weekly', 'month': 'monthly', 'quarter': 'quarterly'}


def _normalize_period(period: str) -> str:
    p = (period or 'weekly').strip().lower()
    p = PERIOD_ALIAS.get(p, p)
    if p not in VALID_REVIEW_PERIODS:
        raise HTTPException(status_code=400, detail='period 仅支持 weekly / monthly / quarterly（别名 week/month/quarter）')
    return p


@app.get("/api/review/generate")
def review_generate_api(
    period: str = Query('weekly', description='weekly/monthly/quarterly'),
    x_backend_token: str = Header(default=""),
):
    """生成并推送周期复盘报告；当日同周期已生成返回 existing=true（幂等）。
    返回 {ok, existing, period, period_start, period_end, report, error?}"""
    require_token(x_backend_token)
    p = _normalize_period(period)
    try:
        result = _review_generate(p, force=False)
    except Exception as e:  # noqa: BLE001
        logger.exception('复盘生成失败')
        return {'ok': False, 'existing': False, 'period': p,
                'period_start': None, 'period_end': None, 'report': None, 'sent': False,
                'error': f'生成失败: {e}'}
    cached = bool(result.get('cached'))
    return {'ok': result.get('ok'), 'existing': cached, 'period': p,
            'period_start': result.get('period_start'), 'period_end': result.get('period_end'),
            'report': result.get('report'), 'sent': not cached, 'error': result.get('reason')}


@app.get("/api/review/latest")
def review_latest_api(
    period: str | None = Query(None, description='可选：weekly/monthly/quarterly（返回该周期最近一份）'),
    x_backend_token: str = Header(default=""),
):
    """最新复盘报告；带 period 时返回该周期最近一份（不存在返回 exists=false）"""
    require_token(x_backend_token)
    if period:
        p = _normalize_period(period)
        report = _review_latest_of(p)
    else:
        report = _review_latest()
    if report is None:
        return {'exists': False, 'report': None, 'reason': '暂无复盘报告'}
    return {'exists': True, 'report': report}


@app.get("/api/review/history")
def review_history_api(limit: int = Query(20, ge=1, le=100), x_backend_token: str = Header(default="")):
    """复盘报告历史（按时间倒序）"""
    require_token(x_backend_token)
    return _review_history(limit)


def register_review_jobs() -> None:
    """注册复盘定时任务：每周日 10:00 周度复盘 / 每月 1 日 10:00 月度复盘（季度手动触发）"""
    from .services.scheduler import add_cron_job

    def _weekly_job() -> None:
        try:
            _review_generate('weekly', force=False)
        except Exception as e:  # noqa: BLE001
            logger.error('定时周度复盘失败: %s', e)

    def _monthly_job() -> None:
        try:
            _review_generate('monthly', force=False)
        except Exception as e:  # noqa: BLE001
            logger.error('定时月度复盘失败: %s', e)

    add_cron_job(_weekly_job, hour=10, minute=0, job_id='review_weekly', day_of_week='sun')
    add_cron_job(_monthly_job, hour=10, minute=0, job_id='review_monthly', day=1)
    logger.info('复盘定时任务已注册（周日 10:00 周度 / 每月1日 10:00 月度）')


# ---------------- 虚拟账本（S15） ----------------

from .services.paper_trading import (  # noqa: E402
    init_account as _pt_init,
    trade as _pt_trade,
    portfolio as _pt_portfolio,
    history as _pt_history,
    trade_from_recommendation as _pt_from_rec,
)


class PaperAccountIn(BaseModel):
    initial_cash: float | None = None


class PaperTradeIn(BaseModel):
    symbol: str
    market: str = 'A股'
    type: str = ''
    side: str | None = None  # 前端兼容别名：type 与 side 二选一
    quantity: float = 100


class PaperFromRecIn(BaseModel):
    recommendation_id: int


def _paper_error(e: Exception) -> HTTPException:
    """虚拟账本错误映射：ValueError -> 400（余额不足/持仓不足/行情失败/市场未开启等）"""
    return HTTPException(status_code=400, detail=str(e))


@app.post("/api/paper/account")
def paper_account_init(data: PaperAccountIn | None = None, x_backend_token: str = Header(default="")):
    """初始化虚拟账户（默认余额=画像投资金额中值；可传 initial_cash 覆盖）；已存在返回现有账户"""
    require_token(x_backend_token)
    return _pt_init(data.initial_cash if data else None)


@app.get("/api/paper/account")
def paper_account_get(x_backend_token: str = Header(default="")):
    """查询虚拟账户：{opened: bool, account: {...} | None}"""
    require_token(x_backend_token)
    from .services.paper_trading import get_account as _pt_get_account
    account = _pt_get_account()
    if account is None:
        return {'opened': False, 'account': None}
    return {'opened': True, 'account': account}


@app.post("/api/paper/trade")
def paper_trade_api(data: PaperTradeIn, x_backend_token: str = Header(default="")):
    """模拟交易：{symbol, market, type: buy|sell, quantity}（type 与 side 二选一）
    成交价=实时现价；买入校验余额与市场；卖出校验持仓并记 pnl（均价成本）"""
    require_token(x_backend_token)
    trade_type = data.type or data.side or ''
    try:
        return _pt_trade(data.symbol, data.market, trade_type, data.quantity)
    except ValueError as e:
        raise _paper_error(e)


@app.get("/api/paper/portfolio")
def paper_portfolio_api(x_backend_token: str = Header(default="")):
    """余额 + 持仓列表（symbol/name/quantity/avg_cost/现价/市值/浮动盈亏）+ 总资产"""
    require_token(x_backend_token)
    return _pt_portfolio()


@app.get("/api/paper/history")
def paper_history_api(limit: int = Query(50, ge=1, le=200), x_backend_token: str = Header(default="")):
    """虚拟账本交易历史（时间倒序）"""
    require_token(x_backend_token)
    return _pt_history(limit)


@app.post("/api/paper/trade-from-recommendation")
def paper_trade_from_rec_api(data: PaperFromRecIn, x_backend_token: str = Header(default="")):
    """一键从推荐买入：按推荐 symbol/entry 中值价买入 1 手（无推荐/余额不足优雅失败，不崩溃）"""
    require_token(x_backend_token)
    try:
        return _pt_from_rec(data.recommendation_id)
    except ValueError as e:
        raise _paper_error(e)



