# -*- coding: utf-8 -*-
"""统一行情数据模型"""

from dataclasses import dataclass


@dataclass
class Quote:
    symbol: str
    name: str
    market: str  # A股/港股/美股
    price: float
    change_pct: float  # 涨跌幅 %
    change: float  # 涨跌额
    open: float
    high: float
    low: float
    prev_close: float
    volume: float  # 股
    amount: float  # 元
    timestamp: str
    source: str
    # ---- S9 基本面扩展（数据源无对应字段时为 0）----
    turnover: float = 0.0  # 换手率 %
    pe: float = 0.0  # 市盈率（TTM，数据源口径）
    total_market_cap: float = 0.0  # 总市值（元）
    float_market_cap: float = 0.0  # 流通市值（元）
    pb: float = 0.0  # 市净率（S10，腾讯 A 股字段 [46]，无数据源时为 0）


@dataclass
class KLineBar:
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
