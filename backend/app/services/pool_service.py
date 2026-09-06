# -*- coding: utf-8 -*-
"""V1.1.0 M1：我的股票池体检（高低位判定，规则实现；AI 点评可选）"""

import json

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection
from ..services.indicators import sma
from .logger import get_app_logger

logger = get_app_logger()


def _position_of(closes: list[float], snap: dict) -> dict:
    """位置判定（图例口径，V1.1.0）：
    - 近 60 日价格区间分位：>0.75 高位 / <0.25 低位 / 其余中位
    - RSI>70 高位警示；RSI<30 低位警示；MA20 乖离率辅助
    返回 {position, position_label, pct, rsi, ma_bias}"""
    position = 'mid'
    pct = 0.5
    rsi = snap.get('rsi14')
    low = min(closes[-60:])
    high = max(closes[-60:])
    if high > low:
        pct = round((closes[-1] - low) / (high - low), 3)
    if pct > 0.75:
        position = 'high'
    elif pct < 0.25:
        position = 'low'
    if rsi is not None:
        if float(rsi) > 70 and position != 'high':
            position = 'high'
        elif float(rsi) < 30 and position != 'low':
            position = 'low'
    ma_bias = None
    ma20 = sma(closes, 20)
    if ma20 and ma20[-1]:
        ma_bias = round((closes[-1] / float(ma20[-1]) - 1) * 100, 2)
    label = {'high': '高位', 'mid': '中位', 'low': '低位'}[position]
    return {'position': position, 'position_label': label, 'pct': pct, 'rsi': rsi, 'ma_bias': ma_bias}


def _rule_verdict(position: str, snap: dict, pe) -> dict:
    """规则结论：值得关注 / 观望 / 回避（一句话理由）"""
    ma = snap.get('ma_status') or ''
    trend = str(snap.get('weekly_trend') or '')
    if position == 'low' and ('多头' in trend or ma == '多头排列'):
        return {'verdict': '值得关注', 'reason': '处于低位区间且周线/均线转多，可研究分批布局机会'}
    if position == 'low':
        return {'verdict': '观望', 'reason': '处于低位区间但趋势尚未转多，等待企稳信号再评估'}
    if position == 'high' and float(rsi if (rsi := snap.get('rsi14')) is not None else 50) > 70:
        return {'verdict': '回避追高', 'reason': '高位且 RSI 超买，追高风险大，宜等回调'}
    if position == 'high':
        return {'verdict': '观望', 'reason': '处于 60 日高位区间，性价比一般，持盈者可考虑分批止盈'}
    return {'verdict': '值得关注', 'reason': '处于中位区间，结合量与趋势择机参与'}


def analyze_pool(groups: list[str] | None = None) -> dict:
    """分析我的股票池：{items:[{symbol,name,market,group,price,change_pct,position...,verdict,reason}], errors}"""
    conn = get_connection()
    try:
        if groups:
            marks = ','.join('?' * len(groups))
            rows = conn.execute(
                f'SELECT symbol, name, market, group_name FROM watchlist WHERE group_name IN ({marks}) '
                'ORDER BY group_name, CAST(symbol AS INTEGER), id',
                groups,
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT symbol, name, market, group_name FROM watchlist ORDER BY group_name, CAST(symbol AS INTEGER), id'
            ).fetchall()
    finally:
        conn.close()

    items: list[dict] = []
    errors: list[str] = []
    # 组市场范围：限定市场的表只分析该市场股票（v1.1.3）
    c2 = get_connection()
    try:
        gm = {r['name']: r['market'] for r in c2.execute('SELECT name, market FROM watch_groups')}
    finally:
        c2.close()
    for r in rows:
        d = dict(r)
        gmarket = gm.get(d['group_name'] or '', '')
        if gmarket and d['market'] != gmarket:
            errors.append(f"{d['name'] or d['symbol']}：表「{d['group_name']}」限 {gmarket}，已跳过（可在管理表中调整范围）")
            continue
        try:
            q = data_fusion.get_quote(d['symbol'], d['market'])
            if q is None:
                errors.append(f"{d['symbol']}：行情获取失败")
                continue
            bars = data_fusion.get_kline(d['symbol'], d['market'], 60)
            if not bars:
                errors.append(f"{d['symbol']}：K线获取失败")
                continue
            closes = [float(b.close) for b in bars]
            from ..services.indicators import indicator_snapshot
            snap = indicator_snapshot(bars) or {}
            pos = _position_of(closes, snap)
            verdict = _rule_verdict(pos['position'], snap, q.pe)
            items.append({
                'symbol': d['symbol'], 'name': d['name'] or q.name or d['symbol'],
                'market': d['market'], 'group': d['group_name'] or '默认',
                'price': q.price, 'change_pct': q.change_pct,
                **pos, **verdict,
                'pe': q.pe,
            })
        except Exception as e:  # noqa: BLE001
            logger.warning('股票池分析 %s 失败: %s', d['symbol'], str(e)[:100])
            errors.append(f"{d['symbol']}：{str(e)[:60]}")
    return {'items': items, 'errors': errors, 'count': len(items)}
