# -*- coding: utf-8 -*-
"""追踪服务（S11）：tracking CRUD + 异动事件查询 + 今日触发统计

- 追踪上限 10 只；market 必须属于系统设置开启的市场（settings.markets）
- symbol+market 唯一（重复 409）；name 为空自动调用行情源补全
- GET 列表时动态统计今日触发次数（tracking_events 当日计数），
  today_triggered 字段由检测引擎维护（跨日按 today_date 重置）
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from .settings_service import get_all_settings


def local_today() -> str:
    """北京时间（UTC+8）当日日期；created_at 以 UTC 存储，今日判断统一走这里"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d')

VALID_MARKETS = ('A股', '港股')
MAX_TRACKING = 10


class TrackingDuplicateError(ValueError):
    """重复添加（symbol+market 已存在）→ HTTP 409"""


class TrackingLimitError(ValueError):
    """追踪数量已达上限 → HTTP 400（带 reason）"""


# 条件字段取值范围（前端校验参考，后端同样兜底）
PRICE_CHANGE_RANGE = (1.0, 10.0)   # 价格急涨急跌阈值 ±1%~10%
VOLUME_RATIO_RANGE = (1.5, 10.0)   # 成交量放大倍数 1.5~10 倍
BIG_ORDER_RANGE = (500_000, 5_000_000)  # 大单近似阈值 50~500 万元

CONDITION_FIELDS = (
    'price_change_pct', 'volume_ratio', 'big_order_amount',
    'tech_signals', 'ai_judge', 'active',
)

TRACKING_COLS = (
    'id', 'symbol', 'name', 'market', 'price_change_pct', 'volume_ratio',
    'big_order_amount', 'tech_signals', 'ai_judge', 'active',
    'today_triggered', 'created_at', 'updated_at',
)


def _row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    d['today_triggered'] = int(d.get('today_triggered') or 0)
    d['tech_signals'] = int(d.get('tech_signals') or 0)
    d['ai_judge'] = int(d.get('ai_judge') or 0)
    d['active'] = int(d.get('active') or 0)
    return d


def _clamp(v: float | None, rng: tuple[float, float], default: float) -> float:
    """数值条件字段限幅（防越界配置）"""
    if v is None:
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return round(max(rng[0], min(rng[1], v)), 4)


def list_tracking() -> list[dict[str, Any]]:
    """全部追踪：含今日触发次数（tracking_events 当日动态统计）与今日事件数"""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(TRACKING_COLS)} FROM tracking ORDER BY id"
        ).fetchall()
        today = local_today()
        result: list[dict[str, Any]] = []
        for r in rows:
            d = _row_to_dict(r)
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM tracking_events "
                "WHERE tracking_id = ? AND substr(created_at, 1, 10) = ?",
                (r['id'], today),
            ).fetchone()['c']
            d['today_events'] = int(cnt)
            result.append(d)
        return result
    finally:
        conn.close()


def get_tracking(item_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(TRACKING_COLS)} FROM tracking WHERE id = ?",
            (item_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def add_tracking(symbol: str, name: str = '', market: str = 'A股',
                 price_change_pct: float | None = None,
                 volume_ratio: float | None = None,
                 big_order_amount: float | None = None,
                 tech_signals: int | None = None,
                 ai_judge: int | None = None) -> dict[str, Any]:
    """添加追踪；校验：总量≤10 / market 开启 / 重复 409 / 自动补名"""
    symbol = (symbol or '').strip().upper()
    market = (market or 'A股').strip()
    if not symbol:
        raise ValueError('股票代码不能为空')

    enabled_markets = get_all_settings().get('markets') or ['A股', '港股']
    if market not in enabled_markets:
        raise ValueError(f'market 未开启: {market}（当前开启: {", ".join(enabled_markets)}）')
    if market not in VALID_MARKETS:
        raise ValueError(f'不支持的 market: {market}（仅支持 A股/港股）')

    name = (name or '').strip()
    if not name:
        q = data_fusion.get_quote(symbol, market)
        if q is None:
            raise ValueError(f'行情获取失败，无法自动补全名称: {symbol}')
        name = q.name or symbol

    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM tracking").fetchone()['c']
        if total >= MAX_TRACKING:
            raise TrackingLimitError(
                f'追踪数量已达上限 {MAX_TRACKING} 只（reason=limit_reached）'
            )

        dup = conn.execute(
            "SELECT 1 FROM tracking WHERE symbol = ? AND market = ? LIMIT 1",
            (symbol, market),
        ).fetchone()
        if dup:
            raise TrackingDuplicateError(f'该股票已在追踪列表中: {symbol}（{market}）')

        now = utc_now()
        cur = conn.execute(
            "INSERT INTO tracking (symbol, name, market, price_change_pct, volume_ratio, "
            "big_order_amount, tech_signals, ai_judge, active, today_triggered, "
            "today_date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)",
            (
                symbol, name, market,
                _clamp(price_change_pct, PRICE_CHANGE_RANGE, 3.0),
                _clamp(volume_ratio, VOLUME_RATIO_RANGE, 3.0),
                _clamp(big_order_amount, BIG_ORDER_RANGE, 1_000_000.0),
                1 if tech_signals is None else (1 if tech_signals else 0),
                1 if ai_judge is None else (1 if ai_judge else 0),
                local_today(), now, now,
            ),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {', '.join(TRACKING_COLS)} FROM tracking WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def update_tracking(item_id: int, **fields) -> dict[str, Any]:
    """更新条件字段 / active（暂停=0 启用=1）；仅更新传入的非 None 字段"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM tracking WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ValueError(f'追踪记录不存在: id={item_id}')

        sets: list[str] = []
        params: list[Any] = []
        if fields.get('price_change_pct') is not None:
            sets.append('price_change_pct = ?')
            params.append(_clamp(fields['price_change_pct'], PRICE_CHANGE_RANGE, 3.0))
        if fields.get('volume_ratio') is not None:
            sets.append('volume_ratio = ?')
            params.append(_clamp(fields['volume_ratio'], VOLUME_RATIO_RANGE, 3.0))
        if fields.get('big_order_amount') is not None:
            sets.append('big_order_amount = ?')
            params.append(_clamp(fields['big_order_amount'], BIG_ORDER_RANGE, 1_000_000.0))
        for f in ('tech_signals', 'ai_judge', 'active'):
            if fields.get(f) is not None:
                sets.append(f'{f} = ?')
                params.append(1 if fields[f] else 0)
        if fields.get('name') is not None:
            sets.append('name = ?')
            params.append((fields['name'] or '').strip())
        if sets:
            sets.append('updated_at = ?')
            params.append(utc_now())
            params.append(item_id)
            conn.execute(
                f"UPDATE tracking SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
        row = conn.execute(
            f"SELECT {', '.join(TRACKING_COLS)} FROM tracking WHERE id = ?",
            (item_id,),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def delete_tracking(item_id: int) -> None:
    """删除追踪（同时删除其事件记录）；不存在抛 ValueError"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tracking_events WHERE tracking_id = ?", (item_id,))
        cur = conn.execute("DELETE FROM tracking WHERE id = ?", (item_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f'追踪记录不存在: id={item_id}')
    finally:
        conn.close()


def list_events(limit: int = 30) -> list[dict[str, Any]]:
    """异动事件历史（含股票名称，按时间倒序）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT e.id, e.tracking_id, e.symbol, e.event_type, e.level, e.price, "
            "e.change_pct, e.detail, e.notified, e.created_at, t.name "
            "FROM tracking_events e LEFT JOIN tracking t ON t.id = e.tracking_id "
            "ORDER BY e.id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def reset_today_triggered() -> int:
    """跨日重置今日触发计数（返回重置行数）；由检测引擎在轮询时调用"""
    conn = get_connection()
    try:
        today = local_today()
        cur = conn.execute(
            "UPDATE tracking SET today_triggered = 0, today_date = ?, updated_at = ? "
            "WHERE today_date IS NULL OR today_date != ?",
            (today, utc_now(), today),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def increment_today_triggered(tracking_id: int) -> None:
    conn = get_connection()
    try:
        today = local_today()
        conn.execute(
            "UPDATE tracking SET today_triggered = today_triggered + 1, "
            "today_date = ?, updated_at = ? WHERE id = ?",
            (today, utc_now(), tracking_id),
        )
        conn.commit()
    finally:
        conn.close()


def last_event_time(tracking_id: int, event_type: str) -> datetime | None:
    """同股同类最近一次事件时间（15 分钟不重复频率控制）"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT created_at FROM tracking_events "
            "WHERE tracking_id = ? AND event_type = ? ORDER BY id DESC LIMIT 1",
            (tracking_id, event_type),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return datetime.fromisoformat(row['created_at'])
    except ValueError:
        return None
