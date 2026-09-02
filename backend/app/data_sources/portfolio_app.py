# -*- coding: utf-8 -*-
"""个人理财软件数据对接（快照文件单数据源）

V1.0.5 起不再直接读取理财软件 finance.db（安全软件误报与耦合问题），
只读取理财软件导出的 portfolio_snapshot.json（v1.10.15+ 自动导出到
用户配置的导出文件夹；默认 = 本软件数据目录 data/portfolio）。
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

SNAPSHOT_FILE = 'portfolio_snapshot.json'

MARKET_MAP = {'hk_stock': '港股', 'a_stock': 'A股', 'us_stock': '美股'}


def detect_snapshot_folder() -> Path | None:
    """快照目录：本软件默认数据目录 data/portfolio（用户在理财软件中把
    AI 导出文件夹指向此处）；为空/不存在返回 None"""
    from ..config import settings
    default_folder = settings.data_dir / 'portfolio'
    if (default_folder / SNAPSHOT_FILE).exists():
        return default_folder
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
    net_worth_history: list = field(default_factory=list)  # 净值历史（近 180 天）
    synced_at: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


def read_snapshot_json() -> FinanceSnapshot | None:
    """读取理财软件导出的 portfolio_snapshot.json（唯一数据源）"""
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
    net_worth_history = data.get('netWorthHistory') or []
    return FinanceSnapshot(
        holdings=holdings,
        accounts=accounts,
        transactions=transactions,
        net_worth=net_worth,
        net_worth_history=net_worth_history,
        synced_at=data.get('exportedAt') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )


def read_snapshot() -> FinanceSnapshot | None:
    """读取快照（JSON 文件，唯一数据源；文件缺失/损坏返回 None）"""
    return read_snapshot_json()
