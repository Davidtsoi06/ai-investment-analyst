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


def _norm_networth(nw: dict | None) -> dict | None:
    """净值字段规范化：camelCase(理财软件/缓存历史) → 前端契约 snake_case"""
    if not isinstance(nw, dict):
        return nw
    return {
        'date': nw.get('date'),
        'total_cash': nw.get('total_cash', nw.get('totalCash')),
        'total_investments': nw.get('total_investments', nw.get('totalInvestments')),
        'net_worth': nw.get('net_worth', nw.get('netWorth')),
    }


def normalize_snapshot_dict(d: dict) -> dict:
    """V1.1.8：缓存快照统一为前端契约字段（snake_case）。
    兼容历史 camelCase 缓存与理财软件导出文件（无需用户重新同步）。"""
    out = dict(d or {})
    nw = out.get('net_worth')
    if isinstance(nw, dict):
        out['net_worth'] = _norm_networth(nw)
    hist = out.get('net_worth_history') or []
    if hist and isinstance(hist[0], dict):
        out['net_worth_history'] = [_norm_networth(x) for x in hist]
    return out


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
        from .finance_reader import finance_db_path
        fdb = finance_db_path()
        return {
            'mode': mode,
            'source': 'finance_db' if fdb is not None else ('snapshot' if snap_file.exists() else 'none'),
            'finance_db_detected': fdb is not None,
            'finance_db': str(fdb) if fdb else None,
            'snapshot_detected': snap_file.exists(),
            'snapshot_dir': str(folder),
            'snapshot_modified_at': datetime.fromtimestamp(snap_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            if snap_file.exists() else None,
            'holdings_count': _count('portfolio_app') if mode == 'snapshot' else _count('manual'),
        }
    finally:
        conn.close()


def sync_now() -> dict:
    """V1.1.7 执行同步：主源=理财软件 finance.db 直读（只读），兜底=快照文件；
    全量替换 source=portfolio_app 的持仓 + 更新账户/净值缓存"""
    mode = get_mode()
    if mode != 'snapshot':
        return {'ok': False, 'reason': '当前为手动录入模式，请在设置中切换为「理财软件直读」后再同步'}
    # 1) finance.db 直读（主源）
    from .finance_reader import read_finance_portfolio
    fb = read_finance_portfolio()
    snapshot = fb.get('snapshot')
    source = fb.get('source') or 'none'
    skipped = fb.get('skipped') or []
    if snapshot is None:
        # 2) 快照文件兜底（旧版理财软件导出仍可用）
        legacy = read_snapshot()
        if legacy is not None:
            snapshot = legacy
            source = 'snapshot'
        else:
            reason = fb.get('error') or '未检测到任何持仓数据来源'
            logger.warning('持仓同步失败：%s', reason)
            return {'ok': False, 'reason': reason,
                    'legacy_reason': '（也未见旧快照文件，可切换「手动录入」模式直接维护持仓）'}

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
        # 快照（账户/交易/净值）存系统设置（V1.1.8：字段规范化 snake_case，前端契约）
        conn.execute(
            'INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)',
            (SNAPSHOT_KEY, json.dumps(normalize_snapshot_dict(snapshot.to_dict()), ensure_ascii=False), now),
        )
        conn.commit()
        logger.info('持仓同步完成：%d 条持仓 / %d 个账户（来源 %s）', len(snapshot.holdings), len(snapshot.accounts), source)
        # V1.1.5：同步后立即用实时行情刷新现价（来源价仅作首次落库兜底）
        try:
            refresh_holdings_prices()
        except Exception:  # noqa: BLE001
            pass
        return {
            'ok': True,
            'mode': mode,
            'source': source,
            'skipped': skipped,
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


# ---------------- V1.1.5：持仓现价实时刷新 ----------------

def refresh_holdings_prices() -> dict:
    """V1.1.5：持仓现价实时刷新（快照/手动来源统一）。
    快照文件只提供 代码/名称/数量/成本；现价由行情数据源实时获取并回写 current_price
    （行情失败保留原值不覆盖，作为 last-known 兜底）。"""
    from concurrent.futures import ThreadPoolExecutor
    from ..data_sources.market.data_fusion import data_fusion

    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT id, symbol, name, market FROM holdings ORDER BY market, symbol'
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {'updated': 0, 'total': 0}

    def _one(row: dict):
        try:
            q = data_fusion.get_quote(row['symbol'], row['market'])
            if q is not None and q.price:
                return row['id'], float(q.price)
        except Exception:  # noqa: BLE001
            pass
        return None

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(rows)))) as ex:
        results = [r for r in ex.map(_one, rows) if r is not None]
    if results:
        conn = get_connection()
        try:
            now = utc_now()
            for rid, price in results:
                conn.execute(
                    'UPDATE holdings SET current_price = ?, updated_at = ? WHERE id = ?',
                    (price, now, rid),
                )
            conn.commit()
        finally:
            conn.close()
        logger.info('持仓现价刷新: %d/%d 只更新', len(results), len(rows))
    return {'updated': len(results), 'total': len(rows)}


def register_price_refresh_job() -> None:
    """注册持仓现价每 5 分钟自动刷新（v1.1.5；行情失败静默保留原值）"""
    from .scheduler import add_interval_job

    def _job() -> None:
        try:
            refresh_holdings_prices()
        except Exception as e:  # noqa: BLE001
            logger.error('定时持仓现价刷新失败: %s', e)

    add_interval_job(_job, minutes=5, job_id='holdings_price_refresh')
    logger.info('已注册每 5 分钟持仓现价刷新任务')
