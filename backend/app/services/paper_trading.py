# -*- coding: utf-8 -*-
"""S15 虚拟账本（纸面交易）：virtual_account + virtual_trades

- 开户：POST /api/paper/account，初始余额 = 画像投资金额中值（10万以下→5万、10-50万→30万、
  50-100万→75万、100万以上→150万）；已存在返回现有账户（幂等）
- 买卖：POST /api/paper/trade {symbol, market, type, quantity}
  买入校验余额（quantity×现价 ≤ balance）与市场（settings.markets）；卖出校验持仓数量；
  成交价 = 现价（data_fusion.get_quote，行情失败拒绝成交）；卖出平仓按均价成本记 pnl
  （同 symbol 多笔买入按均价成本：pnl = (卖出价 - 买入均价) × 数量），并 FIFO 消减买入流水
- 持仓估值：GET /api/paper/portfolio（余额 + 持仓列表 + 总资产）
- 历史：GET /api/paper/history?limit=50
- 一键从推荐买入：POST /api/paper/trade-from-recommendation {recommendation_id}
  按推荐 symbol/入场中值价（无行情时用 entry 中值）买入 1 手（100 股；余额不足按可承受金额折算）
"""

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from ..services.logger import get_app_logger
from ..services.settings_service import get_all_settings

logger = get_app_logger()

LOT = 100  # 1 手 = 100 股


# ---------------- 账户 ----------------

def _get_account_row(conn) -> dict | None:
    row = conn.execute('SELECT * FROM virtual_account ORDER BY id DESC LIMIT 1').fetchone()
    return dict(row) if row else None


def get_account() -> dict | None:
    conn = get_connection()
    try:
        return _get_account_row(conn)
    finally:
        conn.close()


def init_account(initial_cash: float | None = None) -> dict:
    """初始化虚拟账户（默认余额=画像投资金额中值；可传 initial_cash 覆盖）；已存在返回现有（幂等）"""
    from .profile_service import invest_amount_mid
    conn = get_connection()
    try:
        existing = _get_account_row(conn)
        if existing:
            return {'ok': True, 'existing': True, 'account': existing}
        balance = float(initial_cash) if initial_cash else float(invest_amount_mid())
        now = utc_now()
        cur = conn.execute(
            'INSERT INTO virtual_account (balance, initial_balance, created_at) VALUES (?, ?, ?)',
            (balance, balance, now),
        )
        conn.commit()
        row = conn.execute('SELECT * FROM virtual_account WHERE id = ?', (cur.lastrowid,)).fetchone()
        logger.info('虚拟账本开户: id=%s 初始余额=%.2f', cur.lastrowid, balance)
        return {'ok': True, 'existing': False, 'account': dict(row)}
    finally:
        conn.close()


def _require_account(conn) -> dict:
    account = _get_account_row(conn)
    if account is None:
        raise ValueError('虚拟账户尚未开户，请先调用 POST /api/paper/account 初始化')
    return account


# ---------------- 持仓计算 ----------------

def _open_buys(conn, symbol: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM virtual_trades WHERE symbol = ? AND type = 'buy' AND status = 'open' ORDER BY id",
        (symbol,),
    ).fetchall()
    return [dict(r) for r in rows]


def _position(conn, symbol: str) -> dict | None:
    """symbol 的持仓：数量 / 均价成本（按 open 买入流水加权平均）"""
    buys = _open_buys(conn, symbol)
    qty = sum(float(b['quantity']) for b in buys)
    if qty <= 0:
        return None
    cost = sum(float(b['quantity']) * float(b['price']) for b in buys)
    return {'symbol': symbol, 'quantity': qty, 'avg_cost': round(cost / qty, 4)}


def _market_enabled(market: str) -> bool:
    markets = get_all_settings().get('markets') or ['A股', '港股']
    return market in markets


# ---------------- 交易 ----------------

def _get_quote_price(symbol: str, market: str) -> tuple[float, str | None]:
    """现价 + 名称；行情失败抛 ValueError"""
    try:
        q = data_fusion.get_quote(symbol, market)
    except Exception as e:  # noqa: BLE001
        logger.warning('虚拟账本行情获取异常 %s: %s', symbol, str(e)[:80])
        q = None
    if q is None:
        raise ValueError('行情获取失败，无法定价（数据源暂不可用）')
    return float(q.price), q.name or None


def trade(symbol: str, market: str, trade_type: str, quantity: float) -> dict:
    """模拟买卖。trade_type=buy|sell。买入校验余额与市场；卖出校验持仓并记 pnl。"""
    symbol = (symbol or '').strip()
    market = (market or 'A股').strip()
    trade_type = (trade_type or '').strip().lower()
    if not symbol:
        raise ValueError('symbol 不能为空')
    if trade_type not in ('buy', 'sell'):
        raise ValueError('type 仅支持 buy / sell')
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise ValueError('quantity 必须为数字')
    if quantity <= 0:
        raise ValueError('quantity 必须大于 0')

    conn = get_connection()
    try:
        account = _require_account(conn)
        if trade_type == 'buy' and not _market_enabled(market):
            raise ValueError(f'市场「{market}」未开启，请先在设置中启用')

        price, name = _get_quote_price(symbol, market)
        amount = round(price * quantity, 4)
        now = utc_now()

        if trade_type == 'buy':
            if amount > float(account['balance']) + 1e-6:
                raise ValueError(
                    f'余额不足：需要 {amount:,.2f} 元，当前余额 {float(account["balance"]):,.2f} 元')
            conn.execute(
                'INSERT INTO virtual_trades (symbol, name, market, type, quantity, price, amount, '
                'status, pnl, opened_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (symbol, name, market, 'buy', quantity, price, amount, 'open', None, now, None),
            )
            conn.execute(
                'UPDATE virtual_account SET balance = ? WHERE id = ?',
                (round(float(account['balance']) - amount, 4), account['id']),
            )
            conn.commit()
            logger.info('虚拟账本买入 %s %s x%s @ %.4f（%.2f 元）', market, symbol, quantity, price, amount)
            return {'ok': True, 'type': 'buy', 'symbol': symbol, 'name': name, 'market': market,
                    'quantity': quantity, 'price': price, 'amount': amount,
                    'balance': round(float(account['balance']) - amount, 4)}

        # sell
        pos = _position(conn, symbol)
        if pos is None or pos['quantity'] < quantity:
            raise ValueError(
                f'持仓不足：{symbol} 当前持有 {pos["quantity"] if pos else 0} 股，无法卖出 {quantity} 股')
        avg_cost = float(pos['avg_cost'])
        pnl = round((price - avg_cost) * quantity, 4)
        conn.execute(
            'INSERT INTO virtual_trades (symbol, name, market, type, quantity, price, amount, '
            'status, pnl, opened_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (symbol, name, market, 'sell', quantity, price, amount, 'closed', pnl, now, now),
        )
        conn.execute(
            'UPDATE virtual_account SET balance = ? WHERE id = ?',
            (round(float(account['balance']) + amount, 4), account['id']),
        )
        # FIFO 消减买入流水（先买先卖）
        remaining = quantity
        for b in _open_buys(conn, symbol):
            if remaining <= 0:
                break
            b_qty = float(b['quantity'])
            consume = min(b_qty, remaining)
            remaining -= consume
            if consume >= b_qty - 1e-9:
                conn.execute(
                    "UPDATE virtual_trades SET status = 'closed', closed_at = ? WHERE id = ?",
                    (now, b['id']),
                )
            else:
                conn.execute(
                    'UPDATE virtual_trades SET quantity = ? WHERE id = ?',
                    (round(b_qty - consume, 4), b['id']),
                )
        conn.commit()
        logger.info('虚拟账本卖出 %s %s x%s @ %.4f，pnl=%.2f', market, symbol, quantity, price, pnl)
        return {'ok': True, 'type': 'sell', 'symbol': symbol, 'name': name, 'market': market,
                'quantity': quantity, 'price': price, 'amount': amount, 'pnl': pnl,
                'avg_cost': avg_cost,
                'balance': round(float(account['balance']) + amount, 4)}
    finally:
        conn.close()


# ---------------- 持仓估值 ----------------

def portfolio() -> dict:
    """余额 + 持仓列表（symbol/name/quantity/avg_cost/现价/市值/浮动盈亏）+ 总资产"""
    conn = get_connection()
    try:
        account = _get_account_row(conn)
        if account is None:
            return {'ok': False, 'reason': '虚拟账户尚未开户', 'balance': None,
                    'positions': [], 'total_assets': None}
        balance = float(account['balance'])

        # 按 symbol 聚合 open 买入
        rows = conn.execute(
            "SELECT symbol, name, market FROM virtual_trades WHERE type = 'buy' AND status = 'open' "
            "GROUP BY symbol, name, market ORDER BY MIN(id)"
        ).fetchall()
        positions = []
        total_mv = 0.0
        for r in rows:
            sym = r['symbol']
            pos = _position(conn, sym)
            if pos is None:
                continue
            try:
                price, _ = _get_quote_price(sym, r['market'])
            except ValueError:
                price = None
            mv = round(price * pos['quantity'], 4) if price is not None else None
            pnl = round((price - pos['avg_cost']) * pos['quantity'], 4) if price is not None else None
            pnl_pct = round((price / pos['avg_cost'] - 1) * 100, 2) if price is not None and pos['avg_cost'] > 0 else None
            if mv is not None:
                total_mv += mv
            positions.append({
                'symbol': sym,
                'name': r['name'],
                'market': r['market'],
                'quantity': pos['quantity'],
                'avg_cost': pos['avg_cost'],
                'price': price,
                'market_value': mv,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
            })
        return {'ok': True, 'balance': balance, 'positions': positions,
                'total_assets': round(balance + total_mv, 4)}
    finally:
        conn.close()


# ---------------- 历史 ----------------

def history(limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT id, symbol, name, market, type, quantity, price, amount, status, pnl, '
            'recommendation_id, opened_at, closed_at FROM virtual_trades ORDER BY id DESC LIMIT ?',
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------- 一键从推荐买入 ----------------

def _recommendation(conn, recommendation_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, symbol, name, market, rec_type, entry_min, entry_max, valuation_min, "
        "valuation_max, rec_price, status FROM recommendations WHERE id = ?",
        (recommendation_id,),
    ).fetchone()
    return dict(row) if row else None


def _entry_mid(rec: dict) -> float:
    """入场基准价：entry 中值 → 估值中值 → 推荐时价格"""
    if rec.get('entry_min') and rec.get('entry_max'):
        return (float(rec['entry_min']) + float(rec['entry_max'])) / 2
    if rec.get('valuation_min') and rec.get('valuation_max'):
        return (float(rec['valuation_min']) + float(rec['valuation_max'])) / 2
    return float(rec.get('rec_price') or 0)


def trade_from_recommendation(recommendation_id: int) -> dict:
    """按推荐买入 1 手（100 股；余额不足按可承受金额折算，A股按 100 股整数倍）"""
    conn = get_connection()
    try:
        rec = _recommendation(conn, recommendation_id)
        if rec is None:
            return {'ok': False, 'reason': '推荐不存在或已删除', 'recommendation_id': recommendation_id}
        if rec.get('status') == 'closed':
            return {'ok': False, 'reason': '该推荐已结算关闭，无法买入', 'recommendation_id': recommendation_id}

        account = _get_account_row(conn)
        if account is None:
            # 未开户自动开户（一键买入体验）
            from .profile_service import invest_amount_mid
            balance = float(invest_amount_mid())
            now = utc_now()
            cur = conn.execute(
                'INSERT INTO virtual_account (balance, initial_balance, created_at) VALUES (?, ?, ?)',
                (balance, balance, now),
            )
            account = dict(conn.execute(
                'SELECT * FROM virtual_account WHERE id = ?', (cur.lastrowid,)).fetchone())
            logger.info('一键推荐买入前自动开户: id=%s', cur.lastrowid)

        symbol = rec['symbol']
        market = rec['market'] or 'A股'
        if not _market_enabled(market):
            raise ValueError(f'市场「{market}」未开启，请先在设置中启用')

        entry_mid = _entry_mid(rec)
        if entry_mid <= 0:
            return {'ok': False, 'reason': '推荐缺少入场价格，无法买入', 'recommendation_id': recommendation_id}
        try:
            price, name = _get_quote_price(symbol, market)
        except ValueError:
            price, name = entry_mid, rec.get('name')  # 无行情时按 entry 中值价成交

        balance = float(account['balance'])
        # 目标 1 手；不足则按可承受金额折算（A股 100 股整数倍）
        qty = float(LOT)
        if price * qty > balance + 1e-6:
            affordable = int(balance // price)
            if market == 'A股':
                qty = (affordable // LOT) * LOT
            else:
                qty = affordable
        if qty <= 0:
            return {'ok': False, 'reason': f'余额不足：现价 {price:.2f} 元，1 手需 {price * LOT:,.2f} 元，'
                                           f'当前余额 {balance:,.2f} 元',
                    'recommendation_id': recommendation_id}
        amount = round(price * qty, 4)
        now = utc_now()
        conn.execute(
            'INSERT INTO virtual_trades (symbol, name, market, type, quantity, price, amount, '
            'status, pnl, recommendation_id, opened_at, closed_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (symbol, name, market, 'buy', qty, price, amount, 'open', None, recommendation_id,
             now, None),
        )
        conn.execute(
            'UPDATE virtual_account SET balance = ? WHERE id = ?',
            (round(balance - amount, 4), account['id']),
        )
        conn.commit()
        logger.info('一键推荐买入 rec=%s %s %s x%s @ %.4f（%.2f 元）',
                    recommendation_id, market, symbol, qty, price, amount)
        return {'ok': True, 'recommendation_id': recommendation_id, 'type': 'buy',
                'symbol': symbol, 'name': name, 'market': market, 'quantity': qty,
                'price': price, 'amount': amount, 'balance': round(balance - amount, 4)}
    finally:
        conn.close()
