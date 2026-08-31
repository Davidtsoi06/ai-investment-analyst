# -*- coding: utf-8 -*-
"""新浪行情（A股实时，备用源）：hq.sinajs.cn"""

from datetime import datetime

from .http_client import get
from .models import Quote

SINA_URL = 'https://hq.sinajs.cn/list='


def a_quote(symbol: str) -> Quote | None:
    """A股实时行情备用源"""
    prefix = 'sh' if symbol.startswith(('6', '9')) else 'sz'
    text = get(SINA_URL + f'{prefix}{symbol}', encoding='gbk', referer='https://finance.sina.com.cn/')
    try:
        body = text.split('"')[1]
    except IndexError:
        return None
    parts = body.split(',')
    if len(parts) < 10 or not parts[3]:
        return None
    price = float(parts[3])
    prev_close = float(parts[2]) if parts[2] else price
    change_pct = (price / prev_close - 1) * 100 if prev_close else 0.0
    return Quote(
        symbol=symbol,
        name=parts[0],
        market='A股',
        price=price,
        change_pct=round(change_pct, 2),
        change=round(price - prev_close, 2),
        open=float(parts[1]) if parts[1] else price,
        high=float(parts[4]) if parts[4] else price,
        low=float(parts[5]) if parts[5] else price,
        prev_close=prev_close,
        volume=float(parts[8]) if parts[8] else 0.0,
        amount=float(parts[9]) if parts[9] else 0.0,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        source='新浪',
        # S9：新浪源无换手率/PE/市值字段，统一填 0（由腾讯主源提供）
        turnover=0.0,
        pe=0.0,
        total_market_cap=0.0,
        float_market_cap=0.0,
    )