# -*- coding: utf-8 -*-
"""自选股服务（S9）：分组 CRUD + 行情补名

- 分组：group_name 字段（默认组 '默认'），列表按 group_name / sort_order 排序
- 重名校验：同 symbol + market 拒绝重复添加
- 添加时 name 为空则自动调用行情源补全（data_fusion.get_quote）
"""

from typing import Any

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from .logger import get_app_logger

logger = get_app_logger()

VALID_MARKETS = ('A股', '港股')


def list_watchlist() -> list[dict[str, Any]]:
    """全部自选股，按分组名 / 组内排序 / id 排序"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, symbol, name, market, group_name, sort_order, created_at, updated_at "
            "FROM watchlist ORDER BY group_name, sort_order, id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_groups() -> list[str]:
    """去重分组名（按组内最小 id 排序，前端 tab 用）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT group_name FROM watchlist GROUP BY group_name ORDER BY MIN(id)"
        ).fetchall()
        return [r['group_name'] for r in rows]
    finally:
        conn.close()


def _exists(conn, symbol: str, market: str, exclude_id: int | None = None) -> bool:
    if exclude_id is not None:
        row = conn.execute(
            "SELECT 1 FROM watchlist WHERE symbol = ? AND market = ? AND id != ? LIMIT 1",
            (symbol, market, exclude_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM watchlist WHERE symbol = ? AND market = ? LIMIT 1",
            (symbol, market),
        ).fetchone()
    return row is not None


def add_watchlist(symbol: str, name: str = '', market: str = 'A股',
                  group_name: str = '默认') -> dict[str, Any]:
    """添加自选股；重复（symbol+market）抛 ValueError；name 为空时自动查行情补全"""
    symbol = (symbol or '').strip()
    market = (market or 'A股').strip()
    group_name = (group_name or '默认').strip() or '默认'
    if not symbol:
        raise ValueError('股票代码不能为空')
    if market not in VALID_MARKETS:
        raise ValueError(f'不支持的 market: {market}（仅支持 A股/港股）')

    name = (name or '').strip()
    if not name:
        q = data_fusion.get_quote(symbol, market)
        name = q.name if q else symbol

    conn = get_connection()
    try:
        if _exists(conn, symbol, market):
            raise ValueError(f'自选股已存在: {symbol}（{market}）')
        now = utc_now()
        cur = conn.execute(
            "INSERT INTO watchlist (symbol, name, market, group_name, sort_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (symbol, name, market, group_name, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, symbol, name, market, group_name, sort_order, created_at, updated_at "
            "FROM watchlist WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        logger.info('自选股添加: id=%s %s %s（组:%s）', cur.lastrowid, symbol, market, group_name)
        return dict(row)
    finally:
        conn.close()


def update_watchlist(item_id: int, name: str | None = None,
                     group_name: str | None = None,
                     sort_order: int | None = None) -> dict[str, Any]:
    """更新自选股（仅更新传入字段）；记录不存在抛 ValueError"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM watchlist WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ValueError(f'自选股不存在: id={item_id}')

        fields: list[str] = []
        params: list[Any] = []
        if name is not None:
            fields.append('name = ?')
            params.append((name or '').strip())
        if group_name is not None:
            fields.append('group_name = ?')
            params.append((group_name or '默认').strip() or '默认')
        if sort_order is not None:
            fields.append('sort_order = ?')
            params.append(int(sort_order))
        if fields:
            fields.append('updated_at = ?')
            params.append(utc_now())
            params.append(item_id)
            conn.execute(
                f"UPDATE watchlist SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            conn.commit()
        row = conn.execute(
            "SELECT id, symbol, name, market, group_name, sort_order, created_at, updated_at "
            "FROM watchlist WHERE id = ?",
            (item_id,),
        ).fetchone()
        logger.info('自选股更新: id=%s 字段=%s', item_id, fields)
        return dict(row)
    finally:
        conn.close()


def delete_watchlist(item_id: int) -> None:
    """删除自选股；记录不存在抛 ValueError"""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f'自选股不存在: id={item_id}')
        logger.info('自选股删除: id=%s', item_id)
    finally:
        conn.close()