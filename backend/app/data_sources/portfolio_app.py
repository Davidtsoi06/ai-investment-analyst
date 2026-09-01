# -*- coding: utf-8 -*-
"""个人理财软件数据对接（只读，双数据源）

数据源优先级：
1. portfolio_snapshot.json —— 理财软件 v1.10.14+ 导出到用户配置文件夹（本地文件交换，不触发杀毒误报）
2. finance.db —— 直接只读读取（兜底，补充账户/交易/净值数据）
"""

import json
import sqlite3
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / 'AppData' / 'Roaming' / 'personal-finance' / 'finance.db'
SNAPSHOT_FILE = 'portfolio_snapshot.json'

MARKET_MAP = {'hk_stock': '港股', 'a_stock': 'A股', 'us_stock': '美股'}


def detect_db() -> Path | None:
    return DB_PATH if DB_PATH.exists() else None


def _readonly_conn(path: Path) -> sqlite3.Connection:
    """SQLite 只读模式打开（immutable=1：不创建 -shm，WAL 已 checkpoint 场景安全）"""
    uri = 'file:' + urllib.parse.quote(str(path).replace('\\', '/'), safe='/') + '?mode=ro&immutable=1'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def detect_snapshot_folder() -> Path | None:
    """探测理财软件配置的导出文件夹（读 finance.db app_settings，只读）"""
    db = detect_db()
    if db is not None:
        try:
            conn = _readonly_conn(db)
            row = conn.execute("SELECT value FROM app_settings WHERE key = 'aiPortfolio.folder'").fetchone()
            conn.close()
            folder = row['value'] if row else ''
            if folder and (Path(folder) / SNAPSHOT_FILE).exists():
                return Path(folder)
        except Exception:  # noqa: BLE001
            pass
    return None


@dataclass
class FinanceHolding:
    code: str
    name: str
    market: str
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
    synced_at: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


def read_snapshot_json() -> FinanceSnapshot | None:
    """读取理财软件导出的 portfolio_snapshot.json（优先数据源）"""
    folder = detect_snapshot_folder()
    if folder is None:
        return None
    try:
        data = json.loads((folder / SNAPSHOT_FILE).read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None
    holdings: list[FinanceHolding] = []
    for h in data.get('holdings') or []:
        qty = float(h.get('quantity') or 0)
        if qty <= 0:
            continue
        holdings.append(FinanceHolding(
            code=str(h.get('code') or ''),
            name=str(h.get('name') or ''),
            market=MARKET_MAP.get(h.get('market'), str(h.get('market') or '未知')),
            currency=str(h.get('currency') or 'CNY'),
            quantity=qty,
            cost_price=float(h.get('costPrice') or 0),
            current_price=float(h.get('currentPrice') or 0),
            market_value=float(h.get('marketValue') or 0),
            total_cost=float(h.get('totalCost') or 0),
            profit_loss=float(h.get('profitLoss') or 0),
            profit_loss_pct=float(h.get('profitLossPct') or 0),
        ))
    accounts = [
        FinanceAccount(
            name=str(a.get('name') or ''),
            broker=str(a.get('broker') or ''),
            currency=str(a.get('currency') or ''),
            cash_balance=float(a.get('cashBalance') or 0),
        )
        for a in (data.get('accounts') or [])
    ]
    transactions = data.get('transactions') or []
    net_worth = data.get('netWorth') or {}
    return FinanceSnapshot(
        holdings=holdings,
        accounts=accounts,
        transactions=transactions,
        net_worth=net_worth,
        synced_at=data.get('exportedAt') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )


def read_snapshot_db() -> FinanceSnapshot | None:
    """finance.db 直接读取（兜底数据源，补充账户/交易/净值）"""
    path = detect_db()
    if path is None:
        return None
    conn = _readonly_conn(path)
    try:
        holdings: list[FinanceHolding] = []
        for r in conn.execute('SELECT * FROM assets WHERE quantity > 0 ORDER BY market_value DESC'):
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
        nw = conn.execute('SELECT * FROM net_worth_history ORDER BY date DESC LIMIT 1').fetchone()
        return FinanceSnapshot(
            holdings=holdings,
            accounts=accounts,
            transactions=transactions,
            net_worth=dict(nw) if nw else {},
            synced_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
    finally:
        conn.close()


def read_snapshot() -> FinanceSnapshot | None:
    """读取快照：JSON 导出优先，finance.db 兜底"""
    snap = read_snapshot_json()
    if snap is not None and snap.holdings:
        # JSON 快照有持仓时，用 finance.db 补充账户/交易/净值（若快照缺失）
        if not snap.accounts and not snap.transactions and not snap.net_worth:
            db_snap = read_snapshot_db()
            if db_snap is not None:
                snap.accounts = db_snap.accounts
                snap.transactions = db_snap.transactions
                snap.net_worth = db_snap.net_worth
        return snap
    return read_snapshot_db()
