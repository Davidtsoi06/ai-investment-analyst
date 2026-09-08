# -*- coding: utf-8 -*-
"""理财软件 finance.db 只读读取器（V1.1.7 回归直读方案，用户已确认）

安全约束：
- 全程只读（sqlite3 URI mode=ro），绝不写入/修改理财软件数据库
- busy 等待 5 秒（理财软件运行中短暂写锁时容忍）
- 读取前列名校验，理财软件未来改表不致崩溃（缺列即给出可读错误）
- 美股与未知市场持仓跳过并在 skipped 中注明（本软件仅支持 A股/港股）
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from ..data_sources.portfolio_app import FinanceHolding, FinanceAccount, FinanceSnapshot

MARKET_MAP = {'hk_stock': '港股', 'a_stock': 'A股', 'us_stock': '美股'}
_REQUIRED_ASSETS = ('code', 'name', 'market', 'currency', 'quantity', 'cost_price')


def finance_db_hint() -> str:
    """可读路径说明（%APPDATA% 自动随用户名）"""
    return '%APPDATA%\\personal-finance\\finance.db'


def finance_db_path() -> Path | None:
    base = os.environ.get('APPDATA')
    if not base:
        return None
    p = Path(base) / 'personal-finance' / 'finance.db'
    return p if p.exists() else None


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    uri = 'file:' + str(db_path).replace('\\', '/') + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    return conn


def _missing_cols(conn: sqlite3.Connection, table: str, required: tuple[str, ...]) -> list[str]:
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
    except sqlite3.Error:
        return list(required)
    return [c for c in required if c not in cols]


def read_finance_portfolio() -> dict:
    """读 finance.db → {snapshot: FinanceSnapshot|None, skipped: [str], source: str, error: str|None}

    - holdings：assets（a_stock→A股 / hk_stock→港股；跳过美股与数量<=0）
    - accounts：investment_accounts（现金余额）
    - net_worth / net_worth_history：net_worth_history 近 180 天
    - transactions：不读取（用户确认不需要交易记录）
    """
    db_path = finance_db_path()
    if db_path is None:
        return {'snapshot': None, 'skipped': [], 'source': 'none',
                'error': f'未检测到理财软件数据库（{finance_db_hint()}）。请确认本机已安装并运行过「个人理财投资软件」，'
                         '或切换「手动录入」模式'}
    skipped: list[str] = []
    try:
        conn = _ro_connect(db_path)
    except sqlite3.Error as e:
        return {'snapshot': None, 'skipped': [], 'source': 'none',
                'error': f'无法以只读方式打开理财软件数据库：{str(e)[:120]}'}
    try:
        missing = _missing_cols(conn, 'assets', _REQUIRED_ASSETS)
        if missing:
            return {'snapshot': None, 'skipped': [], 'source': 'none',
                    'error': f'理财软件数据库结构不兼容（assets 缺列：{", ".join(missing)}），请升级理财软件后重试'}
        rows = conn.execute(
            'SELECT code, name, market, currency, quantity, cost_price FROM assets ORDER BY market_value DESC'
        ).fetchall()
        holdings: list = []
        for code, name, market, currency, quantity, cost in rows:
            try:
                qty = float(quantity or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty <= 0:
                continue
            mkt = MARKET_MAP.get(str(market or ''), str(market or '未知'))
            if mkt == '美股':
                skipped.append(f'{name or code}({code})：美股暂不支持同步')
                continue
            if mkt not in ('A股', '港股'):
                skipped.append(f'{name or code}({code})：未知市场 {market}')
                continue
            holdings.append(FinanceHolding(
                code=str(code), name=str(name or code), market=mkt,
                currency=str(currency or 'CNY'), quantity=qty,
                cost_price=float(cost or 0),
                current_price=0.0, market_value=0.0, total_cost=0.0,
                profit_loss=0.0, profit_loss_pct=0.0,
            ))
        try:
            acct_cols = _missing_cols(conn, 'investment_accounts', ('name', 'broker', 'currency', 'cash_balance'))
        except sqlite3.Error:
            acct_cols = ['name', 'broker', 'currency', 'cash_balance']
        accounts: list = []
        if not acct_cols:
            for a in conn.execute(
                    'SELECT name, broker, currency, cash_balance FROM investment_accounts ORDER BY id'):
                accounts.append(FinanceAccount(name=str(a[0] or ''), broker=str(a[1] or ''),
                                               currency=str(a[2] or ''), cash_balance=float(a[3] or 0)))
        nw_history: list = []
        try:
            nw_rows = conn.execute(
                'SELECT date, total_cash, total_investments, net_worth '
                'FROM net_worth_history ORDER BY date DESC LIMIT 180').fetchall()
            nw_rows.reverse()
            nw_history = [{'date': str(x[0]), 'totalCash': float(x[1] or 0),
                           'totalInvestments': float(x[2] or 0), 'netWorth': float(x[3] or 0)}
                          for x in nw_rows]
        except sqlite3.Error:
            pass
        net_worth = nw_history[-1] if nw_history else None
        snap = FinanceSnapshot(holdings=holdings, accounts=accounts, transactions=[],
                               net_worth=net_worth, net_worth_history=nw_history,
                               synced_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return {'snapshot': snap, 'skipped': skipped, 'source': 'finance_db', 'error': None}
    except sqlite3.Error as e:
        return {'snapshot': None, 'skipped': [], 'source': 'none',
                'error': f'读取理财软件数据库失败：{str(e)[:120]}（理财软件可能正忙，请稍后重试）'}
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
