# -*- coding: utf-8 -*-
"""多源融合：主源优先 + 自动切换 + 熔断 + 内存缓存"""

import time

from ...services.logger import get_app_logger
from . import tencent_client, sina_client, eastmoney_client, yfinance_client
from .models import Quote, KLineBar

logger = get_app_logger()

CACHE_TTL = 30.0  # 实时行情缓存秒数
KLINE_CACHE_TTL = 3600.0  # 日K缓存 1 小时
FAIL_THRESHOLD = 3  # 连续失败熔断阈值
COOLDOWN_SECONDS = 300.0  # 熔断冷却
FAIL_LOG_INTERVAL = 300.0  # 失败日志节流：同一来源 5 分钟内最多记一次


class DataFusion:
    def __init__(self) -> None:
        self._quote_cache: dict[str, tuple[float, Quote]] = {}
        self._kline_cache: dict[str, tuple[float, list[KLineBar]]] = {}
        self._failures: dict[str, int] = {}
        self._cooldown: dict[str, float] = {}
        self._last_fail_log: dict[str, float] = {}

    # ---- 源编排 ----
    def _quote_sources(self, market: str) -> list[tuple[str, object]]:
        if market == 'A股':
            return [('腾讯', tencent_client.a_quote), ('新浪', sina_client.a_quote)]
        if market == '港股':
            return [('腾讯', tencent_client.hk_quote), ('yfinance', yfinance_client.hk_quote)]
        return []

    def _kline_sources(self, market: str) -> list[tuple[str, object]]:
        if market == 'A股':
            return [('东财', eastmoney_client.get_kline), ('腾讯', tencent_client.get_kline)]
        if market == '港股':
            return [('东财', eastmoney_client.get_kline), ('腾讯', tencent_client.get_kline), ('yfinance', yfinance_client.hk_kline)]
        return []

    # ---- 熔断 ----
    def _is_blocked(self, source_key: str) -> bool:
        return time.time() < self._cooldown.get(source_key, 0)

    def _log_failure_once(self, source_key: str, message: str) -> None:
        """同一来源失败日志节流（FAIL_LOG_INTERVAL 内不重复）"""
        now = time.time()
        if now - self._last_fail_log.get(source_key, 0.0) < FAIL_LOG_INTERVAL:
            return
        self._last_fail_log[source_key] = now
        logger.warning('%s', message)

    def _record_failure(self, source_key: str) -> None:
        count = self._failures.get(source_key, 0) + 1
        self._failures[source_key] = count
        if count >= FAIL_THRESHOLD:
            self._cooldown[source_key] = time.time() + COOLDOWN_SECONDS
            self._failures[source_key] = 0
            self._log_failure_once(
                source_key,
                f'数据源 {source_key} 连续失败 {FAIL_THRESHOLD} 次，熔断 {COOLDOWN_SECONDS:.0f} 秒',
            )
        else:
            self._log_failure_once(source_key, f'数据源 {source_key} 获取失败（第 {count} 次）')

    def _record_success(self, source_key: str) -> None:
        self._failures[source_key] = 0

    def _log_all_failed(self, key: str, kind: str, market: str, symbol: str) -> None:
        """所有数据源均失败：节流记录（行情轮询场景防刷屏）"""
        now = time.time()
        if now - self._last_fail_log.get(key, 0.0) < FAIL_LOG_INTERVAL:
            return
        self._last_fail_log[key] = now
        logger.warning('%s获取失败 %s %s: 所有数据源不可用', kind, market, symbol)

    # ---- 实时行情 ----
    def get_quote(self, symbol: str, market: str) -> Quote | None:
        key = f'{market}:{symbol}'
        cached = self._quote_cache.get(key)
        if cached and time.time() - cached[0] < CACHE_TTL:
            return cached[1]
        for source_name, fn in self._quote_sources(market):
            sk = f'quote:{market}:{source_name}'
            if self._is_blocked(sk):
                continue
            try:
                q = fn(symbol)  # type: ignore[operator]
                if q is not None:
                    self._record_success(sk)
                    self._quote_cache[key] = (time.time(), q)
                    return q
            except Exception:
                self._record_failure(sk)
        self._log_all_failed(key, '行情', market, symbol)
        return None

    # ---- 日K ----
    def get_kline(self, symbol: str, market: str, days: int = 120) -> list[KLineBar] | None:
        key = f'{market}:{symbol}:{days}'
        cached = self._kline_cache.get(key)
        if cached and time.time() - cached[0] < KLINE_CACHE_TTL:
            return cached[1]
        for source_name, fn in self._kline_sources(market):
            sk = f'kline:{market}:{source_name}'
            if self._is_blocked(sk):
                continue
            try:
                bars = fn(market, symbol, days)  # type: ignore[operator]
                if bars:
                    self._record_success(sk)
                    self._kline_cache[key] = (time.time(), bars)
                    return bars
            except Exception:
                self._record_failure(sk)
        self._log_all_failed(key, 'K线', market, symbol)
        return None


data_fusion = DataFusion()
