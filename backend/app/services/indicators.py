# -*- coding: utf-8 -*-
"""S10 技术指标库：MA/EMA/MACD/KDJ/RSI/BOLL/量能/突破/趋势（纯函数，仅用标准库）

约定：
- 序列函数返回与输入等长的列表，预热期元素为 None（便于与 K 线时间轴对齐）。
- 输入 bars 为 list[KLineBar]（data_sources.market.models.KLineBar），
  或直接传价格序列（list[float]）。
- 指标计算全部可单元测试，不依赖网络与外部库。
"""

import math
from typing import Any, Sequence


def sma(values: Sequence[float], period: int) -> list[float | None]:
    """简单移动平均"""
    out: list[float | None] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = round(s / period, 4)
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """指数移动平均（首个有效值取前 period 个的均值作种子）"""
    out: list[float | None] = [None] * len(values)
    if not values:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    prev = seed
    for i, v in enumerate(values):
        if i == period - 1:
            prev = seed
        elif i >= period:
            prev = v * k + prev * (1 - k)
        else:
            out[i] = None
            continue
        out[i] = round(prev, 4)
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD：返回 (DIF, DEA, 柱)。DIF=EMA(fast)-EMA(slow)；DEA=EMA(DIF, signal)；柱=(DIF-DEA)*2"""
    n = len(closes)
    dif: list[float | None] = [None] * n
    dea: list[float | None] = [None] * n
    hist: list[float | None] = [None] * n
    if n < slow + signal:
        return dif, dea, hist
    ef = ema(closes, fast)
    es = ema(closes, slow)
    dif_raw: list[float] = []
    for i in range(n):
        if ef[i] is not None and es[i] is not None:
            d = ef[i] - es[i]  # type: ignore[operator]
            dif[i] = round(d, 4)
            dif_raw.append(d)
    # DEA = EMA(DIF 有效段, signal)
    if len(dif_raw) >= signal:
        dea_raw = ema(dif_raw, signal)
        for j, d in enumerate(dea_raw):
            if d is None:
                continue
            idx = n - len(dif_raw) + j
            dea[idx] = d
    for i in range(n):
        if dif[i] is not None and dea[i] is not None:
            hist[i] = round((dif[i] - dea[i]) * 2, 4)  # type: ignore[operator]
    return dif, dea, hist


def rsi(closes: Sequence[float], period: int = 14) -> list[float | None]:
    """RSI（Wilder 平滑）"""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains += max(diff, 0.0)
        losses += max(-diff, 0.0)
    avg_g = gains / period
    avg_l = losses / period
    for i in range(period, len(closes)):
        diff = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(diff, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-diff, 0.0)) / period
        rs = avg_g / avg_l if avg_l > 0 else float('inf')
        out[i] = round(100 - 100 / (1 + rs), 2)
    return out


def kdj(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        n: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """KDJ：返回 (K, D, J)。RSV=(C-Ln)/(Hn-Ln)*100；K=2/3*Kprev+1/3*RSV；D=2/3*Dprev+1/3*K；J=3K-2D"""
    size = len(closes)
    k_list: list[float | None] = [None] * size
    d_list: list[float | None] = [None] * size
    j_list: list[float | None] = [None] * size
    if size < n:
        return k_list, d_list, j_list
    k_prev = d_prev = 50.0
    for i in range(n - 1, size):
        window_h = max(highs[i - n + 1:i + 1])
        window_l = min(lows[i - n + 1:i + 1])
        rsv = 50.0 if window_h == window_l else (closes[i] - window_l) / (window_h - window_l) * 100
        k = 2 / 3 * k_prev + 1 / 3 * rsv
        d = 2 / 3 * d_prev + 1 / 3 * k
        j = 3 * k - 2 * d
        k_list[i] = round(k, 2)
        d_list[i] = round(d, 2)
        j_list[i] = round(j, 2)
        k_prev, d_prev = k, d
    return k_list, d_list, j_list


def boll(closes: Sequence[float], period: int = 20, k: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """布林带：返回 (中轨, 上轨, 下轨)；标准差为总体标准差"""
    n = len(closes)
    mid: list[float | None] = [None] * n
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if n < period:
        return mid, upper, lower
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / period
        sd = math.sqrt(var)
        mid[i] = round(m, 4)
        upper[i] = round(m + k * sd, 4)
        lower[i] = round(m - k * sd, 4)
    return mid, upper, lower


def cross_above(short_series: Sequence[float | None], long_series: Sequence[float | None]) -> bool:
    """最后一根是否金叉（short 上穿 long）；任一侧数据不足返回 False"""
    if len(short_series) < 2 or len(long_series) < 2:
        return False
    a2, a1 = short_series[-2], short_series[-1]
    b2, b1 = long_series[-2], long_series[-1]
    if a1 is None or a2 is None or b1 is None or b2 is None:
        return False
    return a2 <= b2 and a1 > b1


def vol_ratio(bars: Sequence[Any], n: int = 5) -> float:
    """量比：最后一根成交量 / 前 n 根平均成交量（不足时用可用根数）"""
    if len(bars) < 2:
        return 0.0
    last = float(bars[-1].volume)
    prev = [float(b.volume) for b in bars[-n - 1:-1]]
    prev = [v for v in prev if v > 0]
    if not prev:
        return 0.0
    avg = sum(prev) / len(prev)
    return round(last / avg, 2) if avg > 0 else 0.0


def is_breakout(bars: Sequence[Any], lookback: int = 20, min_vol_ratio: float = 1.2) -> dict:
    """放量突破：今收 > 前 lookback 日最高价，且量比达标、收阳/平"""
    if len(bars) < lookback + 1:
        return {'hit': False, 'ref_high': 0.0, 'vol_ratio': 0.0}
    prev = bars[-lookback - 1:-1]
    ref_high = max(float(b.high) for b in prev)
    last = bars[-1]
    vr = vol_ratio(bars)
    hit = (float(last.close) > ref_high
           and vr >= min_vol_ratio
           and float(last.close) >= float(last.open))
    return {'hit': hit, 'ref_high': round(ref_high, 2), 'vol_ratio': vr}


def ma_status(closes: Sequence[float], fast: int = 5, mid: int = 10, slow: int = 20) -> str:
    """均线形态：多头排列 / 空头排列 / 震荡纠缠"""
    if len(closes) < slow:
        return '震荡纠缠'
    ma5 = sma(closes, fast)
    ma10 = sma(closes, mid)
    ma20 = sma(closes, slow)
    a, b, c = ma5[-1], ma10[-1], ma20[-1]
    if a is None or b is None or c is None:
        return '震荡纠缠'
    if a > b > c:
        return '多头排列'
    if a < b < c:
        return '空头排列'
    return '震荡纠缠'


def _aggregate(bars: Sequence[Any], key_fn) -> list[dict]:
    """按 key_fn 分组合并日 K → 周/月 K（open 取首、close 取末、high 取最大、low 取最小、volume 求和）"""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for b in bars:
        key = key_fn(b.date)
        if key not in groups:
            groups[key] = {'date': key, 'open': float(b.open), 'close': float(b.close),
                           'high': float(b.high), 'low': float(b.low), 'volume': float(b.volume)}
            order.append(key)
        else:
            g = groups[key]
            g['close'] = float(b.close)
            g['high'] = max(g['high'], float(b.high))
            g['low'] = min(g['low'], float(b.low))
            g['volume'] += float(b.volume)
    return [groups[k] for k in order]


def aggregate_weekly(bars: Sequence[Any]) -> list[dict]:
    """日 K → 周 K（ISO 周年）"""
    from datetime import date as _date
    def key_fn(d: str) -> str:
        dt = _date.fromisoformat(d[:10])
        iso = dt.isocalendar()
        return f'{iso[0]}-W{iso[1]:02d}'
    return _aggregate(bars, key_fn)


def aggregate_monthly(bars: Sequence[Any]) -> list[dict]:
    """日 K → 月 K"""
    def key_fn(d: str) -> str:
        return d[:7]
    return _aggregate(bars, key_fn)


def _trend_of(agg_bars: list[dict]) -> str:
    """聚合 K 线的多头/空头/震荡（按收盘均线 5/10 判断）"""
    if len(agg_bars) < 10:
        return '震荡'
    closes = [g['close'] for g in agg_bars]
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    a, b = ma5[-1], ma10[-1]
    if a is None or b is None:
        return '震荡'
    if a > b:
        return '多头'
    if a < b:
        return '空头'
    return '震荡'


def pct_change(values: Sequence[float], days: int) -> float:
    """最近 days 根涨跌幅 %（数据不足返回 0）"""
    if len(values) <= days or values[-days - 1] == 0:
        return 0.0
    return round((values[-1] / values[-days - 1] - 1) * 100, 2)


def indicator_snapshot(bars: Sequence[Any]) -> dict[str, Any]:
    """汇总最新技术指标快照（推荐 Agent 输入；字段缺失时置 None/0）"""
    if not bars:
        return {}
    closes = [float(b.close) for b in bars]
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    last = bars[-1]
    close = closes[-1]

    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    dif, dea, hist = macd(closes)
    rsi14 = rsi(closes)
    k, d, j = kdj(highs, lows, closes)
    mid, upper, lower = boll(closes)
    bd = is_breakout(bars)
    low5 = min(lows[-5:]) if len(lows) >= 5 else min(lows)

    # 布林带位置
    boll_pos = '数据不足'
    if mid[-1] is not None and upper[-1] is not None and lower[-1] is not None:
        if close > upper[-1]:
            boll_pos = '上轨上方'
        elif close > mid[-1]:
            boll_pos = '中上轨'
        elif close > lower[-1]:
            boll_pos = '中下轨'
        else:
            boll_pos = '下轨下方'

    weekly = aggregate_weekly(bars)
    monthly = aggregate_monthly(bars)

    def _v(x):
        return None if x is None else round(float(x), 4)

    return {
        'date': last.date,
        'close': close,
        'chg_pct_5d': pct_change(closes, 5),
        'chg_pct_20d': pct_change(closes, 20),
        'chg_pct_60d': pct_change(closes, 60) if len(closes) > 60 else 0.0,
        'ma5': _v(ma5[-1]), 'ma10': _v(ma10[-1]), 'ma20': _v(ma20[-1]), 'ma60': _v(ma60[-1]),
        'ma_status': ma_status(closes),
        'dif': _v(dif[-1]), 'dea': _v(dea[-1]), 'hist': _v(hist[-1]),
        'macd_golden_cross': cross_above(dif, dea),
        'macd_above_zero': bool(dif[-1] is not None and dif[-1] > 0),
        'rsi14': _v(rsi14[-1]),
        'kdj_k': _v(k[-1]), 'kdj_d': _v(d[-1]), 'kdj_j': _v(j[-1]),
        'kdj_golden_cross': cross_above(k, d),
        'boll_mid': _v(mid[-1]), 'boll_upper': _v(upper[-1]), 'boll_lower': _v(lower[-1]),
        'boll_pos': boll_pos,
        'vol_ratio': bd['vol_ratio'],
        'breakout': bd,
        'low_5d': round(low5, 2),
        'high_60d': round(max(highs[-60:]), 2) if len(highs) >= 60 else round(max(highs), 2),
        'weekly_trend': _trend_of(weekly),
        'monthly_trend': _trend_of(monthly),
    }


def score_short_term(snap: dict[str, Any]) -> int:
    """短线规则评分 0-100：放量突破 + MACD + KDJ + RSI + 均线 + 布林带"""
    if not snap:
        return 0
    score = 0
    signals: list[str] = []
    if snap.get('breakout', {}).get('hit'):
        score += 25
        signals.append(f"放量突破{snap['breakout']['ref_high']}（量比{snap['breakout']['vol_ratio']}）")
    if snap.get('vol_ratio', 0) >= 1.5:
        score += 10
        signals.append(f'成交量放大{snap["vol_ratio"]}倍')
    if snap.get('macd_golden_cross'):
        score += 20
        signals.append('MACD金叉')
    elif snap.get('hist', 0) and snap['hist'] > 0:
        score += 10
    if snap.get('kdj_golden_cross'):
        score += 10
        signals.append('KDJ金叉')
    r = snap.get('rsi14') or 0
    if 45 <= r <= 75:
        score += 10
    ms = snap.get('ma_status', '')
    if ms == '多头排列':
        score += 10
        signals.append('均线多头排列')
    elif ms == '震荡纠缠':
        score += 5
    if snap.get('boll_pos') in ('中上轨', '上轨上方'):
        score += 5
    return min(100, score)


def score_long_term(snap: dict[str, Any], pe: float = 0.0, pb: float = 0.0) -> int:
    """长线规则评分 0-100：周/月线趋势 + 均线 + 中期涨跌幅 + 估值（PE/PB）"""
    if not snap:
        return 0
    score = 0
    if snap.get('weekly_trend') == '多头':
        score += 25
    if snap.get('monthly_trend') == '多头':
        score += 15
    if snap.get('ma_status') == '多头排列':
        score += 15
    if snap.get('chg_pct_60d', 0) > 0:
        score += 10
    if snap.get('chg_pct_20d', 0) > -5:
        score += 5
    if pe > 0:
        if pe <= 15:
            score += 15
        elif pe <= 30:
            score += 10
        elif pe <= 50:
            score += 5
    if pb > 0:
        if pb <= 3:
            score += 10
        elif pb <= 6:
            score += 5
    return min(100, score)
