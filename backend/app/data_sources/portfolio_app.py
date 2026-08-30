# -*- coding: utf-8 -*-
"""个人理财软件 finance.db 只读对接（数据已实测：明文可读，无加密）"""

import sqlite3
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / 'AppData' / 'Roaming' / 'personal-finance' / 'finance.db'

MARKET_MAP = {'hk_stock': '港股', 'a_stock': 'A股', 'us_stock': '美股'}


def detect_db() -> Path | None:
    """检测理财软件数据库是否存在"""
    return DB_PATH if DB_PATH.exists() else None


def _readonly_conn(path: Path) -> sqlite3.Connection:
    """SQLite 只读模式打开（URI 编码路径，支持含空格路径）

    immutable=1：只读主文件、不创建 -shm（WAL 已 checkpoint 场景安全；
    理财软件运行时可能少读未 checkpoint 数据，每小时间隔可接受）。
    """
    uri = 'file:' + urllib.parse.quote(str(path).replace('\\', '/'), safe='/') + '?mode=ro&immutable=1'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class FinanceHolding:
    code: str
    name: str
    market: str  # 港股/A股/美股
    currency: str
    quantity: float
    cost_price: float
    current_price: float
    market_value: float
    total_cost: float
    profit_loss: float
    profit_loss_pct: float


@dataclass
class FinanceAccount:
    name: str
    broker: str
    currency: str
    cash_balance: float


@dataclass
class FinanceSnapshot:
    holdings: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    transactions: list = field(default_factory=list)
    net_worth: dict = field(default_factory=dict)
    synced_at: str = '',

    def to_dict(self) -> dict:
        return asdict(self)


def read_snapshot() -> FinanceSnapshot | None:
    """只读读取完整快照（持仓/账户/交易/净值），仅读取绝不写入"""
    path = detect_db()
    if path is None:
        return None
    conn = _readonly_conn(path)
    try:
        holdings: list[FinanceHolding] = []
        for r in conn.execute(
            'SELECT * FROM assets WHERE quantity > 0 ORDER BY market_value DESC'
        ):
            holdings.append(FinanceHolding(
                code=r['code'],
                name=r['name'],
                market=MARKET_MAP.get(r['market'], r['market'] or '未知'),
                currency=r['currency'],
                quantity=float(r['quantity'] or 0),
                cost_price=float(r['cost_price'] or 0),
                current_price=float(r['current_price'] or 0),
                market_value=float(r['market_value'] or 0),
                total_cost=float(r['total_cost'] or 0),
                profit_loss=float(r['profit_loss'] or 0),
                profit_loss_pct=float(r['profit_loss_pct'] or 0),
            ))
        accounts = [
            FinanceAccount(
                name=r['name'],
                broker=r['broker'] or '',
                currency=r['currency'],
                cash_balance=float(r['cash_balance'] or 0),
            )
            for r in conn.execute('SELECT * FROM investment_accounts ORDER BY id')
        ]
        transactions = [
            dict(r)
            for r in conn.execute('SELECT * FROM transactions ORDER BY date DESC LIMIT 300')
        ]
        nw = conn.execute(
            'SELECT * FROM net_worth_history ORDER BY date DESC LIMIT 1'
        ).fetchone()
        return FinanceSnapshot(
            holdings=holdings,
            accounts=accounts,
            transactions=transactions,
            net_worth=dict(nw) if nw else {},
            synced_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
    finally:
        conn.close()
