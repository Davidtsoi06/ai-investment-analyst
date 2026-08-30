# -*- coding: utf-8 -*-
"""多源融合：主源优先 + 自动切换 + 熔断 + 内存缓存"""

import time

from . import tencent_client, sina_client, eastmoney_client, yfinance_client
from .models import Quote, KLineBar

CACHE_TTL = 30.0  # 实时行情缓存秒数
KLINE_CACHE_TTL = 3600.0  # 日K缓存 1 小时
FAIL_THRESHOLD = 3  # 连续失败熔断阈值
COOLDOWN_SECONDS = 300.0  # 熔断冷却


class DataFusion:
    def __init__(self) -> None:
        self._quote_cache: dict[str, tuple[float, Quote]] = {}
        self._kline_cache: dict[str, tuple[float, list[KLineBar]]] = {}
        self._failures: dict[str, int] = {}
        self._cooldown: dict[str, float] = {}

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

    def _record_failure(self, source_key: str) -> None:
        count = self._failures.get(source_key, 0) + 1
        self._failures[source_key] = count
        if count >= FAIL_THRESHOLD:
            self._cooldown[source_key] = time.time() + COOLDOWN_SECONDS
            self._failures[source_key] = 0

    def _record_success(self, source_key: str) -> None:
        self._failures[source_key] = 0

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
        return None


data_fusion = DataFusion()
