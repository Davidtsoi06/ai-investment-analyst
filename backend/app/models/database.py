# -*- coding: utf-8 -*-
"""SQLite 连接与初始化（WAL 模式，版本化迁移）"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from .tables import SCHEMA_VERSION, TABLES_DDL


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


def init_db() -> None:
    """建表 + 记录迁移版本（幂等）"""
    conn = get_connection()
    try:
        for ddl in TABLES_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT OR IGNORE INTO migrations (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()
