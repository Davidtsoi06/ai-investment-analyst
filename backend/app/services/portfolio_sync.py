# -*- coding: utf-8 -*-
"""持仓数据源服务：快照文件同步 / 手动录入 双模式

模式（system_settings 'portfolio.source_mode'）：
  - snapshot：从理财软件导出的 portfolio_snapshot.json 全量同步（source='portfolio_app'）
  - manual：用户手动录入（source='manual'）
V1.0.5 起不再直接读取理财软件 finance.db。
"""

import json
from datetime import datetime
from pathlib import Path

from ..data_sources.portfolio_app import read_snapshot, SNAPSHOT_FILE
from ..models.database import get_connection, utc_now
from .logger import get_app_logger

logger = get_app_logger()
SNAPSHOT_KEY = 'portfolio_snapshot_v1'
MODE_KEY = 'portfolio.source_mode'


# ---------------- 模式 ----------------

def get_mode() -> str:
    """当前持仓数据模式：snapshot（默认）/ manual"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (MODE_KEY,)).fetchone()
    finally:
        conn.close()
    return (row['value'] if row else 'snapshot') or 'snapshot'


def set_mode(mode: str) -> dict:
    """切换模式；snapshot → manual 时清理历史同步持仓，避免两源混显"""
    mode = 'manual' if mode != 'snapshot' else 'snapshot'
    conn = get_connection()
    try:
        now = utc_now()
        if mode == 'manual':
            conn.execute("DELETE FROM holdings WHERE source = 'portfolio_app'")
            conn.execute('INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)',
                         (MODE_KEY, mode, now))
        else:
            conn.execute('INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)',
                         (MODE_KEY, mode, now))
        conn.commit()
        logger.info('持仓数据模式切换为 %s', mode)
        return {'ok': True, 'mode': mode}
    finally:
        conn.close()


def source_clause(mode: str | None = None) -> tuple[str, list]:
    """按当前模式返回 holdings 过滤 SQL 片段（mode 传 None 自动读取）"""
    m = mode or get_mode()
    src = 'portfolio_app' if m == 'snapshot' else 'manual'
    return "source = ?", [src]


# ---------------- 快照同步 ----------------

def portfolio_status() -> dict:
    """对接状态：快照文件检测 + 当前模式 + 各来源持仓数"""
    mode = get_mode()
    from ..config import settings
    folder = settings.data_dir / 'portfolio'
    snap_file = folder / SNAPSHOT_FILE
    conn = get_connection()
    try:
        def _count(src: str) -> int:
            row = conn.execute('SELECT COUNT(*) AS n FROM holdings WHERE source = ?', (src,)).fetchone()
            return int(row['n'] or 0)
        return {
            'mode': mode,
            'snapshot_detected': snap_file.exists(),
            'snapshot_dir': str(folder),
            'snapshot_modified_at': datetime.fromtimestamp(snap_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            if snap_file.exists() else None,
            'holdings_count': _count('portfolio_app') if mode == 'snapshot' else _count('manual'),
        }
    finally:
        conn.close()


def sync_now() -> dict:
    """执行同步：读取快照文件，全量替换 source=portfolio_app 的持仓 + 更新快照缓存"""
    mode = get_mode()
    if mode != 'snapshot':
        return {'ok': False, 'reason': '当前为手动录入模式，请在设置中切换为「快照文件」后再同步'}
    snapshot = read_snapshot()
    if snapshot is None:
        logger.warning('持仓同步：未检测到快照文件')
        return {'ok': False, 'reason': '未检测到快照文件 portfolio_snapshot.json。请在「个人理财投资软件」设置 → AI 配置 → 导出文件夹，指向本软件数据目录，并触发一次快照导出'}

    conn = get_connection()
    try:
        now = utc_now()
        conn.execute("DELETE FROM holdings WHERE source = 'portfolio_app'")
        for h in snapshot.holdings:
            conn.execute(
                '''INSERT INTO holdings
                (symbol, name, market, currency, quantity, cost_price, current_price, source, sync_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'portfolio_app', ?, ?, ?)'''
                , (
                h.code, h.name, h.market, h.currency, h.quantity, h.cost_price, h.current_price,
                now, now, now,
            ))
        # 快照（账户/交易/净值）存系统设置
        conn.execute(
            'INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)',
            (SNAPSHOT_KEY, json.dumps(snapshot.to_dict(), ensure_ascii=False), now),
        )
        conn.commit()
        logger.info('持仓同步完成：%d 条持仓 / %d 个账户', len(snapshot.holdings), len(snapshot.accounts))
        return {
            'ok': True,
            'mode': mode,
            'holdings': len(snapshot.holdings),
            'accounts': len(snapshot.accounts),
            'transactions': len(snapshot.transactions),
            'net_worth': snapshot.net_worth,
            'synced_at': snapshot.synced_at,
        }
    finally:
        conn.close()


# ---------------- 手动录入 ----------------

def upsert_manual_holding(symbol: str, name: str, market: str, quantity: float,
                          cost_price: float, currency: str = 'CNY') -> dict:
    """手动录入/更新持仓：同 symbol+market 已存在则更新数量与成本价，否则新增"""
    symbol = (symbol or '').strip()
    name = (name or '').strip() or symbol
    market = (market or '').strip()
    if not symbol or market not in ('A股', '港股'):
        return {'ok': False, 'reason': '请输入有效的股票代码，市场仅支持 A股/港股'}
    try:
        quantity = float(quantity)
        cost_price = float(cost_price)
    except (TypeError, ValueError):
        return {'ok': False, 'reason': '数量与成本价必须是数字'}
    if quantity <= 0:
        return {'ok': False, 'reason': '持仓数量必须大于 0'}

    conn = get_connection()
    try:
        now = utc_now()
        row = conn.execute(
            "SELECT id FROM holdings WHERE symbol = ? AND market = ? AND source = 'manual'",
            (symbol, market),
        ).fetchone()
        if row:
            conn.execute(
                '''UPDATE holdings SET name = ?, quantity = ?, cost_price = ?, currency = ?,
                   updated_at = ? WHERE id = ?''',
                (name, quantity, cost_price, currency or 'CNY', now, row['id']),
            )
            action = 'updated'
        else:
            conn.execute(
                '''INSERT INTO holdings
                (symbol, name, market, currency, quantity, cost_price, current_price, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, 'manual', ?, ?)''',
                (symbol, name, market, currency or 'CNY', quantity, cost_price, now, now),
            )
            action = 'created'
        conn.commit()
        logger.info('手动持仓 %s %s（%s）', action, symbol, name)
        return {'ok': True, 'action': action, 'symbol': symbol, 'name': name, 'market': market}
    finally:
        conn.close()


def delete_manual_holding(symbol: str, market: str) -> dict:
    """删除手动持仓（按 symbol+market+source='manual'）"""
    symbol = (symbol or '').strip()
    market = (market or '').strip()
    if not symbol:
        return {'ok': False, 'reason': '股票代码不能为空'}
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM holdings WHERE symbol = ? AND market = ? AND source = 'manual'",
            (symbol, market),
        )
        conn.commit()
        return {'ok': True, 'deleted': cur.rowcount}
    finally:
        conn.close()


def register_hourly_sync() -> None:
    """注册每小时自动同步（整点后 5 分钟；仅快照模式执行）"""
    from .scheduler import add_cron_job

    def _job() -> None:
        try:
            if get_mode() == 'snapshot':
                sync_now()
        except Exception as e:  # noqa: BLE001
            logger.error('定时持仓同步失败: %s', e)

    add_cron_job(_job, hour='*', minute=5, job_id='portfolio_hourly_sync')
    logger.info('已注册每小时持仓同步任务（快照模式）')
