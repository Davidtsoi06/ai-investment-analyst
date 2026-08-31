# -*- coding: utf-8 -*-
"""腾讯行情（A股/港股实时主源 + 日K备用源）：qt.gtimg.cn / web.ifzq.gtimg.cn"""

import json
from datetime import datetime

from .http_client import get
from .models import Quote, KLineBar

TENCENT_URL = 'https://qt.gtimg.cn/q='
KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'


def _parse_a(text: str, symbol: str) -> Quote | None:
    parts = text.split('~')
    if len(parts) < 38 or not parts[3]:
        return None
    price = float(parts[3])
    prev_close = float(parts[4]) if parts[4] else price
    change = float(parts[31]) if len(parts) > 31 and parts[31] else price - prev_close
    change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else (price / prev_close - 1) * 100 if prev_close else 0.0
    # S9 基本面字段（实测 qt.gtimg.cn A股字段索引：[38]换手率% [39]PE [44]流通市值(亿) [45]总市值(亿)）
    turnover = float(parts[38]) if len(parts) > 38 and parts[38] else 0.0
    pe = float(parts[39]) if len(parts) > 39 and parts[39] else 0.0
    float_market_cap = float(parts[44]) * 1e8 if len(parts) > 44 and parts[44] else 0.0
    total_market_cap = float(parts[45]) * 1e8 if len(parts) > 45 and parts[45] else 0.0
    return Quote(
        symbol=symbol,
        name=parts[1],
        market='A股',
        price=price,
        change_pct=round(change_pct, 2),
        change=round(change, 2),
        open=float(parts[5]) if parts[5] else price,
        high=float(parts[33]) if len(parts) > 33 and parts[33] else price,
        low=float(parts[34]) if len(parts) > 34 and parts[34] else price,
        prev_close=prev_close,
        volume=float(parts[6]) * 100 if parts[6] else 0.0,  # 手 -> 股
        amount=float(parts[37]) * 10000 if len(parts) > 37 and parts[37] else 0.0,  # 万元 -> 元
        timestamp=parts[30] if len(parts) > 30 and parts[30] else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        source='腾讯',
        turnover=round(turnover, 2),
        pe=round(pe, 2),
        total_market_cap=round(total_market_cap, 2),
        float_market_cap=round(float_market_cap, 2),
    )


def a_quote(symbol: str) -> Quote | None:
    """A股实时行情，symbol 如 600519（自动加 sh/sz 前缀）"""
    prefix = 'sh' if symbol.startswith(('6', '9')) else 'sz'
    text = get(TENCENT_URL + f'{prefix}{symbol}', encoding='gbk')
    return _parse_a(text, symbol)


def hk_quote(symbol: str) -> Quote | None:
    """港股实时行情，symbol 如 00700"""
    text = get(TENCENT_URL + f'hk{symbol}', encoding='gbk')
    parts = text.split('~')
    if len(parts) < 8 or not parts[3]:
        return None
    price = float(parts[3])
    prev_close = float(parts[4]) if parts[4] else price
    change = price - prev_close
    change_pct = (price / prev_close - 1) * 100 if prev_close else 0.0
    # S9 基本面字段（实测 qt.gtimg.cn 港股：[39]PE [44]/[45]市值(亿)；换手率无对应字段填 0）
    pe = float(parts[39]) if len(parts) > 39 and parts[39] else 0.0
    float_market_cap = float(parts[44]) * 1e8 if len(parts) > 44 and parts[44] else 0.0
    total_market_cap = float(parts[45]) * 1e8 if len(parts) > 45 and parts[45] else 0.0
    return Quote(
        symbol=symbol,
        name=parts[1],
        market='港股',
        price=price,
        change_pct=round(change_pct, 2),
        change=round(change, 2),
        open=float(parts[5]) if parts[5] else price,
        high=price,
        low=price,
        prev_close=prev_close,
        volume=0.0,
        amount=0.0,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        source='腾讯',
        turnover=0.0,
        pe=round(pe, 2),
        total_market_cap=round(total_market_cap, 2),
        float_market_cap=round(float_market_cap, 2),
    )


def get_kline(market: str, symbol: str, days: int = 120) -> list[KLineBar] | None:
    """腾讯日K（A股/港股统一备用源）"""
    if market == 'A股':
        code = ('sh' if symbol.startswith(('6', '9')) else 'sz') + symbol
    elif market == '港股':
        code = 'hk' + symbol
    else:
        return None
    text = get(KLINE_URL, params={'param': f'{code},day,,,{days},qfq'}, encoding='utf-8')
    data = json.loads(text)
    node = (data.get('data') or {}).get(code) or {}
    arr = node.get('qfqday') or node.get('day') or []
    bars: list[KLineBar] = []
    for row in arr[-days:]:
        if not row or len(row) < 6:
            continue
        bars.append(KLineBar(
            date=str(row[0]),
            open=float(row[1]),
            close=float(row[2]),
            high=float(row[3]),
            low=float(row[4]),
            volume=float(row[5]),
            amount=0.0,
        ))
    return bars or None