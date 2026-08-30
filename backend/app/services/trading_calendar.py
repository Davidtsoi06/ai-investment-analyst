# -*- coding: utf-8 -*-
"""交易日历：A股（东财上证指数日K日期集）；港股暂以 A 股近似（后续完善）"""

from datetime import date, timedelta

from ..data_sources.market.eastmoney_client import get_kline
from .logger import get_app_logger

logger = get_app_logger()
_a_days: set[str] | None = None


def _load_a_days() -> set[str]:
    global _a_days
    if _a_days is None:
        try:
            bars = get_kline('A股', '000001', days=200)
            _a_days = {b.date for b in bars} if bars else set()
            logger.info('交易日历加载完成: %d 个交易日', len(_a_days))
        except Exception:  # noqa: BLE001
            logger.warning('交易日历加载失败，降级为工作日判断')
            _a_days = set()
    return _a_days


def is_trading_day(market: str, d: date | None = None) -> bool:
    """判断某日是否为交易日（默认今天）；数据源失败时降级为周一~周五"""
    d = d or date.today()
    if d.weekday() >= 5:
        return False
    days = _load_a_days()
    if not days:
        return True  # 降级：工作日视为交易日
    return d.isoformat() in days
