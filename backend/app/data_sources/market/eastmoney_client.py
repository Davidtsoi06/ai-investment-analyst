# -*- coding: utf-8 -*-
"""东方财富（日K，A股/港股主源）：push2his kline 接口"""

from datetime import datetime, timedelta

from .http_client import get
from .models import KLineBar

KLINE_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'


def _secid(market: str, symbol: str) -> str:
    if market == 'A股':
        # 沪市：6xx 股票 / 9xx B股 / 5xx ETF；其余（0/1/2/3 开头）为深市
        return f'1.{0}'.format(symbol) if symbol.startswith(('6', '9', '5')) else f'0.{0}'.format(symbol)
    if market == '港股':
        return f'116.{0}'.format(symbol)
    raise ValueError(f'不支持的 market: {0}'.format(market))


def get_kline(market: str, symbol: str, days: int = 120) -> list[KLineBar] | None:
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=days * 2)).strftime('%Y%m%d')
    params = {
        'secid': _secid(market, symbol),
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': 101,
        'fqt': 1,
        'beg': start,
        'end': end,
    }
    import json
    text = get(KLINE_URL, params=params)
    data = json.loads(text)
    klines = (data.get('data') or {}).get('klines') or []
    bars: list[KLineBar] = []
    for line in klines[-days:]:
        p = line.split(',')
        if len(p) < 6:
            continue
        bars.append(KLineBar(
            date=p[0],
            open=float(p[1]),
            close=float(p[2]),
            high=float(p[3]),
            low=float(p[4]),
            volume=float(p[5]),
            amount=float(p[6]) if len(p) > 6 and p[6] else 0.0,
        ))
    return bars or None
