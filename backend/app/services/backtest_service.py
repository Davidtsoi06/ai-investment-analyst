# -*- coding: utf-8 -*-
"""S10 推荐回测统计：未结算推荐自动评估（短线 5 个交易日 / 长线 20 个交易日），
汇总胜率 / 平均收益 / 止损率 / 分类型 / 分月报告（需求文档 模块三：推荐记录与回测）

结算规则（窗口内逐日检查）：
- 先触止损（最低价 ≤ 止损价）→ outcome='stop'，按止损价计收益
- 再触目标（最高价 ≥ 目标价）→ outcome='win'，按目标价计收益
- 窗口走完 → 按末日收盘计 outcome=win/loss/flat
评估数据源默认 data_fusion（可注入 provider 便于单元测试）。
"""

from datetime import date

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from ..services.logger import get_app_logger

logger = get_app_logger()

HORIZON = {'短线': 5, '长线': 20}  # 评估窗口（交易日）

REC_FIELDS = ('id', 'symbol', 'name', 'market', 'rec_type', 'entry_min', 'entry_max',
              'stop_loss', 'target', 'valuation_min', 'valuation_max',
              'confidence', 'logic', 'risk_level', 'rec_date', 'rec_price', 'status')


def _entry_price(rec: dict) -> float:
    """入场基准价：入场区间中值，否则推荐时价格"""
    if rec.get('entry_min') and rec.get('entry_max'):
        return (float(rec['entry_min']) + float(rec['entry_max'])) / 2
    if rec.get('valuation_min') and rec.get('valuation_max'):
        return (float(rec['valuation_min']) + float(rec['valuation_max'])) / 2
    return float(rec.get('rec_price') or 0)


def _evaluate_one(rec: dict, bars: list) -> dict | None:
    """对单条推荐结算；数据不足返回 None（跳过）"""
    horizon = HORIZON.get(rec.get('rec_type'), 5)
    entry = _entry_price(rec)
    if entry <= 0 or not bars:
        return None
    # 找到推荐日之后的第一个交易日
    start = None
    for i, b in enumerate(bars):
        if str(b.date)[:10] >= str(rec.get('rec_date', ''))[:10]:
            start = i
            break
    if start is None:
        return None
    window = bars[start:start + horizon]
    if not window:
        return None

    stop = float(rec['stop_loss']) if rec.get('stop_loss') else None
    target = float(rec['target']) if rec.get('target') else None
    outcome = 'flat'
    result_price = float(window[-1].close)
    for b in window:
        if stop is not None and float(b.low) <= stop:
            outcome = 'stop'
            result_price = stop
            break
        if target is not None and float(b.high) >= target:
            outcome = 'win'
            result_price = target
            break
    else:
        result_pct = (result_price / entry - 1) * 100
        if result_pct > 0.001:
            outcome = 'win'
        elif result_pct < -0.001:
            outcome = 'loss'

    return {
        'recommendation_id': rec['id'],
        'result_price': round(result_price, 4),
        'result_pct': round((result_price / entry - 1) * 100, 2),
        'outcome': outcome,
        'entry_price': round(entry, 4),
        'eval_days': len(window),
        'horizon': rec.get('rec_type'),
    }


def evaluate_pending(provider=None) -> dict:
    """评估全部 open 推荐；provider(symbol, market) -> list[KLineBar]（默认 data_fusion.get_kline）"""
    get_bars = provider or (lambda s, m: data_fusion.get_kline(s, m, 300))
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT " + ', '.join(REC_FIELDS) + " FROM recommendations WHERE status = 'open' ORDER BY id"
        ).fetchall()
        recs = [dict(r) for r in rows]
        evaluated = 0
        skipped: list[dict] = []
        now = utc_now()
        for rec in recs:
            # 当天推荐的收盘前不结算（避免用当日半日K提前判定）
            if str(rec.get('rec_date', ''))[:10] >= date.today().isoformat():
                skipped.append({'id': rec['id'], 'symbol': rec['symbol'], 'reason': '推荐日当天不结算'})
                continue
            try:
                bars = get_bars(rec['symbol'], rec['market'])
                perf = _evaluate_one(rec, bars or [])
            except Exception as e:  # noqa: BLE001
                logger.warning('推荐 %d 回测评估失败: %s', rec['id'], str(e)[:100])
                skipped.append({'id': rec['id'], 'symbol': rec['symbol'], 'reason': '行情获取失败'})
                continue
            if perf is None:
                skipped.append({'id': rec['id'], 'symbol': rec['symbol'], 'reason': 'K线数据不足'})
                continue
            conn.execute(
                '''INSERT INTO recommendation_performance
                (recommendation_id, result_price, result_pct, outcome, entry_price, eval_days, horizon, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (perf['recommendation_id'], perf['result_price'], perf['result_pct'], perf['outcome'],
                 perf['entry_price'], perf['eval_days'], perf['horizon'], now),
            )
            conn.execute(
                "UPDATE recommendations SET status = 'closed' WHERE id = ?",
                (rec['id'],),
            )
            evaluated += 1
        conn.commit()
    finally:
        conn.close()
    logger.info('推荐回测结算: 评估 %d 条 / 跳过 %d 条', evaluated, len(skipped))
    return {'evaluated': evaluated, 'skipped': skipped}


# ---------------- 统计报告 ----------------

def _stats_of(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {'count': 0, 'win_rate': None, 'avg_return': None, 'total_return': 0.0,
                'wins': 0, 'losses': 0, 'stops': 0, 'flats': 0}
    wins = sum(1 for r in rows if r['outcome'] == 'win')
    losses = sum(1 for r in rows if r['outcome'] == 'loss')
    stops = sum(1 for r in rows if r['outcome'] == 'stop')
    flats = sum(1 for r in rows if r['outcome'] == 'flat')
    returns = [float(r['result_pct']) for r in rows]
    return {
        'count': n,
        'win_rate': round(wins / n * 100, 1),
        'avg_return': round(sum(returns) / n, 2),
        'total_return': round(sum(returns), 2),
        'wins': wins, 'losses': losses, 'stops': stops, 'flats': flats,
    }


def get_backtest_report() -> dict:
    """回测报告：先结算未评估推荐，再汇总统计"""
    evaluate_pending()
    conn = get_connection()
    try:
        rows = conn.execute(
            '''SELECT r.id, r.symbol, r.name, r.market, r.rec_type, r.confidence, r.rec_date, r.rec_price,
                      p.outcome, p.result_pct, p.result_price, p.entry_price, p.eval_days, p.horizon, p.evaluated_at
               FROM recommendation_performance p
               JOIN recommendations r ON r.id = p.recommendation_id
               ORDER BY p.id DESC'''
        ).fetchall()
        perf = [dict(r) for r in rows]
        summary = _stats_of(perf)

        by_type = {}
        for rec_type in ('短线', '长线'):
            by_type[rec_type] = _stats_of([r for r in perf if r['rec_type'] == rec_type])

        by_month: list[dict] = []
        months: dict[str, list] = {}
        for r in perf:
            months.setdefault(str(r['rec_date'])[:7], []).append(r)
        for m in sorted(months, reverse=True)[:6]:
            st = _stats_of(months[m])
            by_month.append({'month': m, **st})

        recent = [
            {k: r[k] for k in ('id', 'symbol', 'name', 'rec_type', 'rec_date', 'confidence',
                               'outcome', 'result_pct', 'result_price', 'entry_price', 'eval_days')}
            for r in perf[:20]
        ]
        return {'summary': summary, 'by_type': by_type, 'by_month': by_month, 'recent': recent}
    finally:
        conn.close()


def recommendation_history(limit: int = 50) -> list[dict]:
    """推荐历史（含回测结果），按推荐日期倒序"""
    conn = get_connection()
    try:
        rows = conn.execute(
            '''SELECT r.id, r.symbol, r.name, r.market, r.rec_type, r.confidence, r.logic, r.risk_level,
                      r.rec_date, r.rec_price, r.status,
                      p.outcome, p.result_pct, p.result_price, p.eval_days
               FROM recommendations r
               LEFT JOIN recommendation_performance p
                      ON p.id = (SELECT id FROM recommendation_performance WHERE recommendation_id = r.id ORDER BY id DESC LIMIT 1)
               ORDER BY r.rec_date DESC, r.id DESC LIMIT ?''',
            (min(limit, 200),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
