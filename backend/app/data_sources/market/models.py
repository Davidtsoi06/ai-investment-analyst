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


@dataclass
class KLineBar:
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
