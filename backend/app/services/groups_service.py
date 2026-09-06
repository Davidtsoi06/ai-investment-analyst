# -*- coding: utf-8 -*-
"""V1.1.3 我的股票池：表（组）元数据管理（独立一等实体）"""

from ..models.database import get_connection, utc_now
from .logger import get_app_logger

logger = get_app_logger()


def list_groups() -> list[dict]:
    """组列表：watch_groups 元数据优先；旧版仅在 watchlist 行出现的组自动补元数据返回"""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT name, market, note, sort_order, created_at FROM watch_groups ORDER BY sort_order, name'
        ).fetchall()
        groups = {r['name']: dict(r) for r in rows}
        used = conn.execute(
            'SELECT DISTINCT group_name FROM watchlist WHERE group_name IS NOT NULL'
        ).fetchall()
        changed = False
        now = utc_now()
        for u in used:
            name = u['group_name']
            if name not in groups:
                conn.execute(
                    'INSERT OR IGNORE INTO watch_groups (name, market, note, sort_order, created_at, updated_at) '
                    'VALUES (?, ?, ?, 0, ?, ?)',
                    (name, '', '', now, now),
                )
                groups[name] = {'name': name, 'market': '', 'note': '', 'sort_order': 0}
                changed = True
        if changed:
            conn.commit()
        counts = {r['group_name']: int(r['n']) for r in conn.execute(
            'SELECT group_name, COUNT(*) n FROM watchlist GROUP BY group_name')}
    finally:
        conn.close()
    out = []
    for name, g in groups.items():
        d = dict(g)
        d['count'] = counts.get(name, 0)
        out.append(d)
    return sorted(out, key=lambda x: (x.get('sort_order') or 0, x['name']))


def create_group(name: str, market: str = '', note: str = '') -> dict:
    name = (name or '').strip()
    if not name:
        return {'ok': False, 'reason': '表名不能为空'}
    market = (market or '').strip()
    conn = get_connection()
    try:
        now = utc_now()
        cur = conn.execute(
            'INSERT OR IGNORE INTO watch_groups (name, market, note, sort_order, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)',
            (name, market, (note or '').strip(), now, now),
        )
        if cur.rowcount == 0:
            conn.execute('UPDATE watch_groups SET market = ?, note = ?, updated_at = ? WHERE name = ?',
                         (market, (note or '').strip(), now, name))
        conn.commit()
        return {'ok': True, 'group': {'name': name, 'market': market, 'note': (note or '').strip()}}
    finally:
        conn.close()


def update_group(old_name: str, name: str | None = None, market: str | None = None,
                 note: str | None = None) -> dict:
    """改名/改市场范围/改备注；改名时同步 watchlist 行"""
    old_name = (old_name or '').strip()
    new_name = ((name or '').strip() or old_name)
    conn = get_connection()
    try:
        now = utc_now()
        row = conn.execute('SELECT * FROM watch_groups WHERE name = ?', (old_name,)).fetchone()
        if row is None:
            return {'ok': False, 'reason': f'表「{old_name}」不存在'}
        cur = dict(row)
        if new_name != old_name:
            exists = conn.execute('SELECT 1 FROM watch_groups WHERE name = ?', (new_name,)).fetchone()
            if exists:
                return {'ok': False, 'reason': f'表「{new_name}」已存在'}
            conn.execute('UPDATE watch_groups SET name = ?, updated_at = ? WHERE name = ?',
                         (new_name, now, old_name))
            conn.execute('UPDATE watchlist SET group_name = ?, updated_at = ? WHERE group_name = ?',
                         (new_name, now, old_name))
        conn.execute(
            'UPDATE watch_groups SET market = ?, note = ?, updated_at = ? WHERE name = ?',
            (cur['market'] if market is None else (market or '').strip(),
             cur['note'] if note is None else (note or '').strip(), now, new_name))
        conn.commit()
        return {'ok': True, 'group': {'name': new_name}}
    finally:
        conn.close()


def delete_group(name: str) -> dict:
    name = (name or '').strip()
    conn = get_connection()
    try:
        cur = conn.execute('DELETE FROM watch_groups WHERE name = ?', (name,))
        conn.execute('DELETE FROM watchlist WHERE group_name = ?', (name,))
        conn.commit()
        return {'ok': True, 'deleted': cur.rowcount}
    finally:
        conn.close()
