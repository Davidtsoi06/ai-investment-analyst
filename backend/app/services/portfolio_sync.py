# -*- coding: utf-8 -*-
"""持仓同步服务：finance.db（只读）-> 本地 holdings 表 + 快照存储"""

import json

from ..data_sources.portfolio_app import detect_db, read_snapshot
from ..models.database import get_connection, utc_now
from .logger import get_app_logger

logger = get_app_logger()
SNAPSHOT_KEY = 'portfolio_snapshot_v1'


def portfolio_status() -> dict:
    """对接状态：是否检测到理财软件数据库"""
    db = detect_db()
    return {'detected': db is not None, 'db_path': str(db) if db else None}


def sync_now() -> dict:
    """执行同步：全量替换 source=portfolio_app 的持仓 + 更新快照"""
    snapshot = read_snapshot()
    if snapshot is None:
        logger.warning('持仓同步：未检测到理财软件数据库')
        return {'ok': False, 'reason': '未检测到个人理财软件数据库（AppData/Roaming/personal-finance/finance.db）'}

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
            'holdings': len(snapshot.holdings),
            'accounts': len(snapshot.accounts),
            'transactions': len(snapshot.transactions),
            'net_worth': snapshot.net_worth,
            'synced_at': snapshot.synced_at,
        }
    finally:
        conn.close()


def register_hourly_sync() -> None:
    """注册每小时自动同步（整点后 5 分钟）"""
    from .scheduler import add_cron_job

    def _job() -> None:
        try:
            sync_now()
        except Exception as e:  # noqa: BLE001
            logger.error('定时持仓同步失败: %s', e)

    add_cron_job(_job, hour='*', minute=5, job_id='portfolio_hourly_sync')
    logger.info('已注册每小时持仓同步任务')
