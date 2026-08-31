# -*- coding: utf-8 -*-
"""SQLite 连接与初始化（WAL 模式，版本化迁移）"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from .tables import SCHEMA_VERSION, TABLES_DDL, MIGRATIONS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """获取数据库连接（调用方负责关闭）"""
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    try:
        rows = conn.execute('SELECT version FROM migrations').fetchall()
        return {r['version'] for r in rows}
    except sqlite3.OperationalError:
        return set()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r['name'] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}
    except sqlite3.OperationalError:
        return set()


def _apply_migrations(conn: sqlite3.Connection) -> int:
    """幂等执行未应用的迁移；返回本次应用版本数"""
    applied = 0
    for version in sorted(MIGRATIONS):
        if version in _applied_versions(conn):
            continue
        for step in MIGRATIONS[version]:
            kind = step.get('kind')
            if kind == 'add_column':
                if step['column'] not in _columns(conn, step['table']):
                    conn.execute(step['ddl'])
            elif kind == 'sql':
                conn.execute(step['ddl'])
        conn.execute(
            'INSERT OR REPLACE INTO migrations (version, applied_at) VALUES (?, ?)',
            (version, utc_now()),
        )
        conn.commit()
        applied += 1
    return applied


def init_db() -> None:
    """建表 + 版本化迁移（幂等）"""
    conn = get_connection()
    try:
        for ddl in TABLES_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT OR IGNORE INTO migrations (version, applied_at) VALUES (?, ?)",
            (1, utc_now()),
        )
        _apply_migrations(conn)
        conn.commit()
    finally:
        conn.close()
