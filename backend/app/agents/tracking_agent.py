# -*- coding: utf-8 -*-
"""异动检测引擎（S11）：单股异动检测 + 事件持久化 + 分级通知

检测项（对应需求模块四）：
  ① 价格急涨急跌：当前价 vs 上次轮询价，按实际间隔折算 5 分钟窗口涨跌幅；
     |涨跌| ≥ 2×阈值 或 跌幅 ≥5% → 紧急，否则 → 关注
  ② 成交量放大：quote.volume vs 近 5 日均量（日K 20 根）× 阈值（按已交易时间折算）→ 关注
  ③ 大单成交近似：免费接口无逐笔，用两次轮询间成交额增量 |amount - prev_amount| 近似 → 关注
  ④ 技术信号：MACD 金叉/死叉、RSI>70 超买 / <30 超卖（复用 services/indicators.py）→ 关注
  ⑤ 突破关键位：close 上穿/下穿 MA20 / MA60 → 关注
  ⑥ AI 判断：对触发事件用 DeepSeek 生成 2-3 句分析（无 Key / 失败降级为模板文本）

频率控制：同一股票同一事件类型 15 分钟不重复（查 tracking_events 冷却）；
通知：services/notification.send_notification(type='alert')，紧急豁免免打扰。
"""

import time
from datetime import datetime, time as dtime, timezone, timedelta

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from ..services.indicators import macd, rsi, cross_above, sma
from ..services.notification import send_notification
from ..services.tracking_service import (
    list_tracking,
    reset_today_triggered,
    increment_today_triggered,
    last_event_time,
)
from ..services.logger import get_app_logger

logger = get_app_logger()

# ---------------- 交易时段（A股 09:30-11:30/13:00-15:00；港股 09:30-12:00/13:00-16:00） ----------------

MARKET_SESSIONS: dict[str, list[tuple[tuple[int, int], tuple[int, int]]]] = {
    'A股': [((9, 30), (11, 30)), ((13, 0), (15, 0))],
    '港股': [((9, 30), (12, 0)), ((13, 0), (16, 0))],
}


def _to_minutes(h: int, m: int) -> int:
    return h * 60 + m


def _session_ranges(market: str) -> list[tuple[int, int]]:
    return [(_to_minutes(*s), _to_minutes(*e)) for s, e in MARKET_SESSIONS.get(market, [])]


def is_trading_time(market: str, now: datetime | None = None) -> bool:
    """当前是否处于交易时段（不含午休）"""
    now = now or datetime.now()
    t = now.hour * 60 + now.minute
    return any(s <= t <= e for s, e in _session_ranges(market))


def session_elapsed_fraction(market: str, now: datetime | None = None) -> float:
    """当日已交易时间占全天比例 0..1（午休不计入；非交易时段返回 0）"""
    now = now or datetime.now()
    t = now.hour * 60 + now.minute
    total = 0
    elapsed = 0
    for s, e in _session_ranges(market):
        total += e - s
        if s <= t <= e:
            elapsed += t - s
        elif t > e:
            elapsed += e - s
    return round(elapsed / total, 4) if total > 0 else 0.0


# ---------------- 上一轮快照缓存（内存 dict；key=f"{market}:{symbol}"） ----------------

prev_snapshots: dict[str, dict] = {}


def _snap_key(market: str, symbol: str) -> str:
    return f'{market}:{symbol}'


def _store_snapshot(market: str, symbol: str, price: float, amount: float) -> None:
    prev_snapshots[_snap_key(market, symbol)] = {
        'price': float(price),
        'amount': float(amount),
        'ts': time.time(),
    }


def clear_snapshots() -> None:
    prev_snapshots.clear()


# ---------------- 单股检测 ----------------

EVENT_TYPE_CN = {
    'price_surge': '价格急涨',
    'price_drop': '价格急跌',
    'volume_spike': '放量异动',
    'big_order': '大单成交',
    'tech_signal': '技术信号',
    'ma_break': '突破均线',
}

COOLDOWN_SECONDS = 15 * 60  # 同股同类（非涨跌幅类）15 分钟不重复


def _volume_check(track: dict, quote, kline) -> dict | None:
    """放量检测：当日累计成交量 vs 近 5 日均量（日K 20 根，排除当日），按已交易时间折算"""
    if not kline or len(kline) < 6 or quote.volume <= 0:
        return None
    today = datetime.now().date().isoformat()
    bars = [b for b in kline if b.date[:10] != today]  # 排除当日未收盘 bar
    prev = bars[-20:] if len(bars) >= 20 else bars
    vols = [float(b.volume) for b in prev if float(b.volume) > 0]
    if not vols:
        return None
    avg_vol = sum(vols) / len(vols)
    if is_trading_time(track['market']):
        # 交易时段内：期望量随时间线性增长，按已交易时间折算阈值
        fraction = max(session_elapsed_fraction(track['market']), 0.05)  # 开盘初期兜底
    else:
        # 非交易时段（手动检测）：当日累计量已定格，用全时段基准
        fraction = 1.0
    threshold = float(track['volume_ratio']) * fraction
    ratio = quote.volume / avg_vol
    if ratio >= threshold and ratio >= 1.5:
        return {
            'event_type': 'volume_spike',
            'level': '关注',
            'detail': (f'成交量 {quote.volume / 10000:.0f} 万股，为近5日均量 {ratio:.1f} 倍'
                       f'（阈值 {track["volume_ratio"]:.1f} 倍，按已交易时间 {fraction * 100:.0f}% 折算）'),
        }
    return None


def _big_order_check(track: dict, quote, prev: dict | None) -> dict | None:
    """大单近似：两次轮询间成交额增量 ≥ 阈值（免费接口无逐笔，用成交额突变近似）"""
    if prev is None or prev.get('amount') is None or quote.amount <= 0:
        return None
    delta = abs(float(quote.amount) - float(prev['amount']))
    threshold = float(track['big_order_amount'])
    if delta >= threshold:
        return {
            'event_type': 'big_order',
            'level': '关注',
            'detail': (f'轮询间隔成交额 {delta / 10000:.0f} 万元 ≥ 大单阈值 {threshold / 10000:.0f} 万元'
                       f'（免费接口无逐笔成交，以成交额增量近似）'),
        }
    return None


def _tech_check(track: dict, kline) -> list[dict]:
    """技术信号：MACD 金叉/死叉、RSI 超买/超卖"""
    if not kline or len(kline) < 40:
        return []
    closes = [float(b.close) for b in kline]
    dif, dea, hist = macd(closes)
    events: list[dict] = []
    if cross_above(dif, dea):
        events.append({'event_type': 'tech_signal', 'level': '关注', 'detail': 'MACD 金叉'})
    elif cross_above(dea, dif):
        events.append({'event_type': 'tech_signal', 'level': '关注', 'detail': 'MACD 死叉'})
    r = rsi(closes)
    if r[-1] is not None:
        if r[-1] > 70:
            events.append({'event_type': 'tech_signal', 'level': '关注', 'detail': f'RSI {r[-1]:.1f} 超买（>70）'})
        elif r[-1] < 30:
            events.append({'event_type': 'tech_signal', 'level': '关注', 'detail': f'RSI {r[-1]:.1f} 超卖（<30）'})
    return events


def _ma_break_check(track: dict, kline) -> list[dict]:
    """突破关键位：close 上穿/下穿 MA20 / MA60"""
    if not kline or len(kline) < 22:
        return []
    closes = [float(b.close) for b in kline]
    events: list[dict] = []
    for period, label in ((20, 'MA20'), (60, 'MA60')):
        if len(closes) < period + 2:
            continue
        ma = sma(closes, period)
        c1, c2 = closes[-2], closes[-1]
        m1, m2 = ma[-2], ma[-1]
        if None in (m1, m2):
            continue
        if c1 < m1 and c2 > m2:  # type: ignore[operator]
            events.append({'event_type': 'ma_break', 'level': '关注', 'detail': f'收盘价上穿 {label}（{m2:.2f}）'})
        elif c1 > m1 and c2 < m2:  # type: ignore[operator]
            events.append({'event_type': 'ma_break', 'level': '关注', 'detail': f'收盘价下穿 {label}（{m2:.2f}）'})
    return events


def check_tracking(track: dict, prev: dict | None, quote=None, kline=None) -> list[dict]:
    """单股异动检测：返回触发事件列表（未持久化）。
    prev 为上一轮快照 {'price','amount','ts'}（无则仅价格/大单项跳过）；
    quote/kline 可由调用方传入（轮询已拉取），为空时内部拉取。
    """
    if quote is None:
        quote = data_fusion.get_quote(track['symbol'], track['market'])
    if quote is None:
        return []
    if kline is None:
        kline = data_fusion.get_kline(track['symbol'], track['market'], 120)

    events: list[dict] = []
    price = float(quote.price)
    change_pct = float(quote.change_pct or 0.0)
    threshold = float(track['price_change_pct'])

    # ① 当日涨跌幅超阈值（相对昨收；上涨/下跌都触发，交易时段内由轮询检查）
    if threshold > 0 and abs(change_pct) >= threshold:
        if change_pct > 0:
            etype = 'price_surge'
            label = '上涨'
        else:
            etype = 'price_drop'
            label = '下跌'
        urgent = abs(change_pct) >= 2 * threshold
        events.append({
            'event_type': etype,
            'level': '紧急' if urgent else '关注',
            'price': price,
            'change_pct': round(change_pct, 2),
            'detail': (f'当日{label} {change_pct:+.2f}%（相对昨收），'
                       f'超过提醒阈值 ±{threshold:.1f}%'),
        })

    # ② 成交量放大
    ev = _volume_check(track, quote, kline)
    if ev is not None:
        ev['price'] = price
        ev['change_pct'] = round(change_pct, 2)
        events.append(ev)

    # ③ 大单成交近似
    ev = _big_order_check(track, quote, prev)
    if ev is not None:
        ev['price'] = price
        ev['change_pct'] = round(change_pct, 2)
        events.append(ev)

    # ④ 技术信号
    if track['tech_signals']:
        for ev in _tech_check(track, kline):
            ev['price'] = price
            ev['change_pct'] = round(change_pct, 2)
            events.append(ev)

    # ⑤ 突破关键位
    for ev in _ma_break_check(track, kline):
        ev['price'] = price
        ev['change_pct'] = round(change_pct, 2)
        events.append(ev)

    return events


# ---------------- AI 判断与持久化 ----------------

def _ai_comment(track: dict, event: dict) -> str:
    """AI 综合判断：对触发事件生成 2-3 句分析；无 Key / 失败降级模板文本"""
    if not track.get('ai_judge'):
        return ''
    try:
        from ..services.llm_client import chat
        from ..services.settings_service import get_ai_key
        if not get_ai_key():
            return '价格波动超过阈值，请关注。'
        prompt = (
            f'你是A股/港股盘中异动分析助手。股票 {track["symbol"]}（{track["name"] or ""}）'
            f'触发异动：{EVENT_TYPE_CN.get(event["event_type"], event["event_type"])}，'
            f'级别{event["level"]}，现价 {event.get("price")}，'
            f'详情：{event.get("detail", "")}。请用 2-3 句中文给出客观分析（可能原因与关注点），'
            f'不要给出买卖建议。'
        )
        text = chat(
            [
                {'role': 'system', 'content': '你是严谨的股票异动分析助手，输出简洁客观。'},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        return (text or '').strip()[:300]
    except Exception as e:  # noqa: BLE001
        logger.warning('AI 异动分析失败，降级模板: %s', e)
        return '价格波动超过阈值，请关注。'


def _day_event_done(tracking_id: int, event_type: str) -> bool:
    """当日（本地 0 点起，存储为 UTC）是否已触发过该股该类型事件（涨跌幅提醒每交易日一次）"""
    try:
        local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        utc_start = (local_midnight - timedelta(hours=8)).strftime('%Y-%m-%dT%H:%M:%S')
    except Exception:  # noqa: BLE001
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM tracking_events "
            "WHERE tracking_id = ? AND event_type = ? AND substr(created_at, 1, 19) >= ?",
            (tracking_id, event_type, utc_start),
        ).fetchone()
        return int(row['n'] or 0) > 0
    finally:
        conn.close()


def persist_event(track: dict, event: dict) -> dict | None:
    """事件入库 + 今日触发计数 + 分级通知。
    - price_surge / price_drop（当日涨跌幅提醒）：每个交易日每股最多提醒一次；
    - 其它类型：同股同类 15 分钟冷却。
    返回入库事件 dict；冷却/已提醒期内返回 None。
    """
    if event['event_type'] in ('price_surge', 'price_drop'):
        if _day_event_done(track['id'], event['event_type']):
            return None
    else:
        last = last_event_time(track['id'], event['event_type'])
        if last is not None:
            if last.tzinfo is not None:
                last = last.astimezone().replace(tzinfo=None)  # UTC 存储 → 本地 naive
            dt = (datetime.now() - last).total_seconds()
            if dt < COOLDOWN_SECONDS:
                return None

    ai_text = _ai_comment(track, event)
    detail = event.get('detail', '')
    if ai_text:
        detail = f"{detail}；AI 分析：{ai_text}" if detail else f"AI 分析：{ai_text}"

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tracking_events (tracking_id, symbol, event_type, level, price, "
            "change_pct, detail, notified, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                track['id'], track['symbol'], event['event_type'], event['level'],
                event.get('price'), event.get('change_pct'), detail, utc_now(),
            ),
        )
        conn.commit()
        event_id = cur.lastrowid
    finally:
        conn.close()

    increment_today_triggered(track['id'])

    level = event['level']
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = f'【{level}】{track["symbol"]} {EVENT_TYPE_CN.get(event["event_type"], event["event_type"])}'
    content = (
        f'时间：{now_str}\n'
        f'股票：{track["name"] or track["symbol"]}（{track["symbol"]}）\n'
        f'类型：{EVENT_TYPE_CN.get(event["event_type"], event["event_type"])}\n'
        f'现价：{event.get("price", "-")}（当日 {event.get("change_pct", 0):+.2f}%）\n'
        f'详情：{detail}'
    )
    r = send_notification('alert', title, content, level=level, force=(level == '紧急'))

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE tracking_events SET notified = ? WHERE id = ?",
            (1 if r.get('sent') else 0, event_id),
        )
        conn.commit()
    finally:
        conn.close()

    row = conn_row(event_id)
    return row


def conn_row(event_id: int):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, tracking_id, symbol, event_type, level, price, change_pct, detail, notified, created_at "
            "FROM tracking_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------- 全量检测（手动 / 轮询共用） ----------------

def _run_all(manual: bool, tracks: list | None = None) -> dict:
    reset_today_triggered()
    if tracks is None:
        tracks = [t for t in list_tracking() if t['active']]
    results: list[dict] = []
    triggered = 0
    for t in tracks:
        item: dict = {'symbol': t['symbol'], 'market': t['market'], 'name': t['name'], 'events': []}
        try:
            quote = data_fusion.get_quote(t['symbol'], t['market'])
            if quote is None:
                item['error'] = '行情获取失败'
                results.append(item)
                continue
            kline = data_fusion.get_kline(t['symbol'], t['market'], 120)
            prev = prev_snapshots.get(_snap_key(t['market'], t['symbol']))
            events = check_tracking(t, prev, quote, kline)
            saved = []
            for ev in events:
                row = persist_event(t, ev)
                if row is not None:
                    saved.append(row)
                    triggered += 1
            item['events'] = saved
            item['triggered'] = len(saved)
            _store_snapshot(t['market'], t['symbol'], quote.price, quote.amount)
        except Exception as e:  # noqa: BLE001
            logger.warning('异动检测失败 %s/%s: %s', t['market'], t['symbol'], e)
            item['error'] = str(e)[:200]
        results.append(item)
    return {
        'ok': True,
        'mode': 'manual' if manual else 'poll',
        'checked': len(tracks),
        'triggered': triggered,
        'results': results,
        'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def run_check() -> dict:
    """POST /api/tracking/check：手动触发一次全量检测（返回检测结果，便于测试与演示）"""
    return _run_all(manual=True)


def poll_once(tracks: list | None = None) -> dict:
    """轮询调度单次执行（交易时段/节流过滤由 scheduler 负责，可传入候选列表）"""
    return _run_all(manual=False, tracks=tracks)
