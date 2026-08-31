# -*- coding: utf-8 -*-
"""追踪轮询调度（S11）：APScheduler interval 任务，交易时段内轮询异动检测

- interval 30 秒（需求：A股 10~30 秒；港股 1~5 分钟 → 港股在轮询内按 90 秒节流）
- 仅当存在 active 追踪时注册（add_tracking 后动态补注册）
- 每次轮询：交易日 + 交易时段判断（非交易时段跳过）；失败单只跳过不中断
"""

from datetime import datetime

from ..services.logger import get_app_logger
from ..services.trading_calendar import is_trading_day
from ..agents.tracking_agent import poll_once, is_trading_time

logger = get_app_logger()

POLL_INTERVAL_SECONDS = 30          # 全市场轮询节奏（A 股 10~30 秒档）
HK_THROTTLE_SECONDS = 90.0          # 港股节流（需求 1~5 分钟，取 90 秒）
_JOB_ID = 'tracking_poll'

_hk_last: dict[str, float] = {}     # 港股 symbol → 上次拉取时间


def _has_active_tracking() -> bool:
    from ..services.tracking_service import list_tracking
    return any(t['active'] for t in list_tracking())


def _hk_ok(symbol: str) -> bool:
    """港股节流：同一只港股两次轮询间隔 ≥ 90 秒；通过则记录本次时间"""
    import time
    now = time.time()
    if now - _hk_last.get(symbol, 0.0) < HK_THROTTLE_SECONDS:
        return False
    _hk_last[symbol] = now
    return True


def _poll_job() -> None:
    """单次轮询：交易日 + 交易时段 + 港股节流过滤；非交易时段跳过"""
    try:
        if not _has_active_tracking():
            return
        now = datetime.now()
        if not is_trading_day('A股'):
            return
        from ..services.tracking_service import list_tracking
        eligible: list = []
        for t in list_tracking():
            if not t['active']:
                continue
            if not is_trading_time(t['market'], now):
                continue
            if t['market'] == '港股' and not _hk_ok(t['symbol']):
                continue
            eligible.append(t)
        if not eligible:
            return
        result = poll_once(eligible)
        if result.get('triggered'):
            logger.info('轮询异动触发 %d 条（检测 %d 只）', result['triggered'], result['checked'])
    except Exception as e:  # noqa: BLE001
        logger.warning('追踪轮询异常: %s', e)


def start_tracking_polling() -> bool:
    """注册 30 秒 interval 轮询任务（仅当存在 active 追踪）；返回是否注册"""
    from ..services.scheduler import scheduler
    if scheduler.get_job(_JOB_ID) is not None:
        return True
    if not _has_active_tracking():
        return False
    scheduler.add_job(
        _poll_job, 'interval', seconds=POLL_INTERVAL_SECONDS,
        id=_JOB_ID, replace_existing=True,
        next_run_time=datetime.now(),
    )
    logger.info('追踪轮询任务已注册（%d 秒，交易时段内执行）', POLL_INTERVAL_SECONDS)
    return True


def ensure_tracking_polling() -> bool:
    """追踪增删后确保轮询任务存在（有 active 追踪才注册）"""
    return start_tracking_polling()


def stop_tracking_polling() -> None:
    from ..services.scheduler import scheduler
    job = scheduler.get_job(_JOB_ID)
    if job is not None:
        job.remove()
        logger.info('追踪轮询任务已移除')
