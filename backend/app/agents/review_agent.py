# -*- coding: utf-8 -*-
"""S15 投资复盘 Agent：周/月/季复盘报告（操作盈亏汇总 / 最佳·最差 / 行为分析 AI 研判 + 规则降级 / 改进建议）
→ 存档 review_reports（当日同周期幂等）+ 推送应用内通知（type='review'）

数据收集：
  - 持仓盈亏：holdings × 实时行情（data_fusion）
  - 交易记录：理财软件快照 portfolio_snapshot_v1.transactions（近 N 条，按区间过滤；资产名/代码
    通过 finance.db 只读 assets 表补全，失败降级为 asset_id）
  - 推荐回测：backtest_service.get_backtest_report()（胜率/平均收益/累计收益）
  - 跟踪事件数：tracking_events（区间内，北京时间）
  - 净值历史：finance.db net_worth_history 只读（区间初 vs 最新，月度对比）；失败降级快照最新净值

行为分析（模块八）：
  - 有 Key：DeepSeek 基于 交易频率/持仓集中/推荐跟随率/已实现盈亏 等特征输出
    追涨杀跌/过度交易/处置效应/确认偏差/锚定效应 判断与建议（严格 JSON）
  - 无 Key / AI 失败：规则统计描述（交易频率偏高→过度交易风险、集中度过高、亏损持仓占比→锚定成本价等）

定时：每周日 10:00 weekly / 每月 1 日 10:00 monthly（main.py register_review_jobs）；季度由 API 手动触发。
"""

import json
from datetime import datetime, timezone, timedelta

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from ..services.logger import get_agent_logger
from ..services.notification import send_notification
from ..utils.prompts.review_prompt import build_review_prompt, parse_ai_output

logger = get_agent_logger()

PERIOD_DAYS = {'weekly': 7, 'monthly': 30, 'quarterly': 90}
PERIOD_CN = {'weekly': '周度', 'monthly': '月度', 'quarterly': '季度'}
DISCLAIMER = '⚠️ 本报告由 AI 自动生成，仅供参考，不构成投资建议。'

_running: dict[str, bool] = {}


# ---------------- 时间工具 ----------------

def _beijing_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=8)


def _local_today() -> str:
    return _beijing_now().strftime('%Y-%m-%d')


def _window(period: str) -> tuple[str, str]:
    """周期数据窗口：周=最近7天、月=最近30天、季=最近90天（含当日）"""
    days = PERIOD_DAYS.get(period, 7)
    end = _beijing_now()
    start = end - timedelta(days=days - 1)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def _beijing_date(iso: str) -> str | None:
    """UTC ISO -> 北京时间日期；解析失败返回 None"""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone(timedelta(hours=8)))
    return dt.strftime('%Y-%m-%d')


# ---------------- 数据收集 ----------------

def _load_holdings() -> list[dict]:
    """本地持仓 + 实时行情估值：市值 / 浮动盈亏（行情失败跳过估值）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT symbol, name, market, quantity, cost_price, current_price FROM holdings ORDER BY market, symbol"
        ).fetchall()
    finally:
        conn.close()
    result: list[dict] = []
    for r in rows:
        h = dict(r)
        try:
            q = data_fusion.get_quote(h['symbol'], h['market'])
        except Exception:  # noqa: BLE001
            q = None
        if q is None:
            result.append({**h, 'price': None, 'market_value': None, 'pnl': None})
            continue
        price = float(q.price)
        qty = float(h.get('quantity') or 0)
        cost = float(h.get('cost_price') or 0)
        result.append({
            **h,
            'price': price,
            'market_value': round(price * qty, 2),
            'pnl': round((price - cost) * qty, 2) if cost > 0 else None,
        })
    return result


def _asset_map() -> dict[int, dict]:
    """finance.db assets 只读映射 asset_id -> {code, name, market}；失败返回空表"""
    try:
        from ..data_sources.portfolio_app import _readonly_conn, detect_db
        path = detect_db()
        if path is None:
            return {}
        conn = _readonly_conn(path)
        try:
            result: dict[int, dict] = {}
            for r in conn.execute('SELECT id, code, name, market FROM assets'):
                result[int(r['id'])] = {'code': r['code'], 'name': r['name'], 'market': r['market']}
            return result
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning('资产映射读取失败（降级 asset_id）: %s', str(e)[:100])
        return {}


def _load_transactions(period_start: str, period_end: str) -> list[dict]:
    """快照 transactions（按区间过滤，倒序）→ 补全资产名/代码 + 配对已实现盈亏（均价成本法）"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'portfolio_snapshot_v1'"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return []
    try:
        snapshot = json.loads(row['value'])
    except (ValueError, TypeError):
        return []
    raw = snapshot.get('transactions') or []
    asset_map = _asset_map()

    # 区间内交易（date 为 YYYY-MM-DD）；快照新格式自带 assetCode/assetName（不依赖 finance.db）
    items: list[dict] = []
    for t in raw:
        d = str(t.get('date') or '')[:10]
        if not (period_start <= d <= period_end):
            continue
        code = t.get('assetCode') or t.get('asset_code') or ''
        name = t.get('assetName') or t.get('asset_name') or ''
        market = t.get('market') or ''
        if not code and not name:
            asset = asset_map.get(int(t.get('asset_id') or 0)) or {}
            code = asset.get('code') or ''
            name = asset.get('name') or ''
            market = asset.get('market') or ''
        items.append({
            'asset_id': t.get('asset_id'),
            'symbol': code,
            'name': name,
            'market': market,
            'type': t.get('type'),
            'quantity': float(t.get('quantity') or 0),
            'price': float(t.get('price') or 0),
            'amount': float(t.get('total_amount') or 0),
            'date': d,
        })
    items.sort(key=lambda x: x['date'], reverse=True)

    # 已实现盈亏：按 asset_id 均价成本配对（同标的多次买入取均价）
    buy_qty: dict[int, float] = {}
    buy_cost: dict[int, float] = {}
    for t in items:
        aid = t['asset_id']
        if t['type'] == 'buy':
            buy_qty[aid] = buy_qty.get(aid, 0) + t['quantity']
            buy_cost[aid] = buy_cost.get(aid, 0) + t['quantity'] * t['price']
    for t in items:
        t['pnl'] = None
        if t['type'] == 'sell':
            aid = t['asset_id']
            avg = buy_cost.get(aid, 0) / buy_qty[aid] if buy_qty.get(aid) else 0
            t['pnl'] = round((t['price'] - avg) * t['quantity'], 2)
    return items[:100]


def _load_backtest() -> dict:
    """推荐回测统计（自动先结算未评估推荐）"""
    try:
        from ..services.backtest_service import get_backtest_report
        report = get_backtest_report()
        return report.get('summary') or {}
    except Exception as e:  # noqa: BLE001
        logger.warning('推荐回测统计失败: %s', str(e)[:100])
        return {}


def _load_tracking_events(period_start: str, period_end: str) -> int:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT created_at FROM tracking_events ORDER BY id DESC LIMIT 500"
        ).fetchall()
    finally:
        conn.close()
    count = 0
    for r in rows:
        d = _beijing_date(r['created_at'])
        if d and period_start <= d <= period_end:
            count += 1
    return count


def _load_net_worth(period_start: str) -> dict:
    """净值：优先快照净值历史（180 天，理财软件导出），其次 finance.db；最后降级最新值"""
    result: dict = {'latest': None, 'start': None, 'change_pct': None}

    def _from_history(history: list) -> None:
        items = []
        for h in history:
            try:
                d = str(h.get('date') or '')[:10]
                v = float(h.get('netWorth') or h.get('net_worth') or 0)
                if d and v > 0:
                    items.append((d, v))
            except (TypeError, ValueError):
                continue
        items.sort(key=lambda x: x[0])
        if not items:
            return
        result['latest'] = round(items[-1][1], 2)
        for d, v in items:
            if d >= period_start:
                result['start'] = round(v, 2)
                break
        if result['start'] is None:
            result['start'] = round(items[0][1], 2)
        if result['latest'] and result['start'] and float(result['start']) > 0:
            result['change_pct'] = round((float(result['latest']) / float(result['start']) - 1) * 100, 2)

    snap_row = None
    conn = get_connection()
    try:
        snap_row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'portfolio_snapshot_v1'"
        ).fetchone()
    finally:
        conn.close()
    if snap_row:
        try:
            snap = json.loads(snap_row['value'])
            _from_history(snap.get('net_worth_history') or [])
        except (ValueError, TypeError):
            pass
    if result['latest'] is None:
        try:
            from ..data_sources.portfolio_app import _readonly_conn, detect_db
            path = detect_db()
            if path is not None:
                conn = _readonly_conn(path)
                try:
                    history = [
                        dict(r) for r in conn.execute(
                            'SELECT date, net_worth FROM net_worth_history ORDER BY date DESC LIMIT 180'
                        )
                    ]
                finally:
                    conn.close()
                _from_history(history)
        except Exception as e:  # noqa: BLE001
            logger.warning('净值历史读取失败: %s', str(e)[:100])
    if result['latest'] is None and snap_row:
        try:
            nw = json.loads(snap_row['value']).get('net_worth') or {}
            if nw.get('netWorth') or nw.get('net_worth'):
                result['latest'] = round(float(nw.get('netWorth') or nw.get('net_worth')), 2)
        except (ValueError, TypeError):
            pass
    return result


def build_features(period: str) -> dict:
    """汇总全部统计特征（供报告与行为分析使用）"""
    period_start, period_end = _window(period)
    holdings = _load_holdings()
    trades = _load_transactions(period_start, period_end)
    backtest = _load_backtest()
    tracking_events = _load_tracking_events(period_start, period_end)
    net_worth = _load_net_worth(period_start)

    buy_count = sum(1 for t in trades if t['type'] == 'buy')
    sell_count = sum(1 for t in trades if t['type'] == 'sell')
    window_days = PERIOD_DAYS.get(period, 7)
    trades_per_day = round((buy_count + sell_count) / window_days, 2)
    realized = sum(t['pnl'] or 0 for t in trades if t['pnl'] is not None)
    win_sells = sum(1 for t in trades if t['pnl'] is not None and t['pnl'] > 0)
    loss_sells = sum(1 for t in trades if t['pnl'] is not None and t['pnl'] < 0)

    total_mv = sum(h['market_value'] for h in holdings if h.get('market_value') is not None)
    top_weight = 0.0
    if total_mv > 0 and holdings:
        top_weight = round(
            max((h['market_value'] or 0) for h in holdings) / total_mv * 100, 1)

    # 推荐跟随率：当前 open 推荐中已持有的比例
    conn = get_connection()
    try:
        recs = conn.execute(
            "SELECT symbol FROM recommendations WHERE status = 'open'"
        ).fetchall()
    finally:
        conn.close()
    rec_symbols = {r['symbol'] for r in recs}
    held_symbols = {h['symbol'] for h in holdings}
    followed = len(rec_symbols & held_symbols)
    follow_rate = round(followed / len(rec_symbols) * 100, 1) if rec_symbols else 0.0
    open_rec_count = len(rec_symbols)

    loss_positions = sum(1 for h in holdings if h.get('pnl') is not None and h['pnl'] < 0)
    holding_count = len(holdings)

    return {
        'period_start': period_start,
        'period_end': period_end,
        'holdings': holdings,
        'trades': trades,
        'backtest': backtest,
        'tracking_events': tracking_events,
        'net_worth': net_worth,
        'buy_count': buy_count,
        'sell_count': sell_count,
        'trades_per_day': trades_per_day,
        'realized_pnl': round(realized, 2),
        'win_sells': win_sells,
        'loss_sells': loss_sells,
        'top_holding_weight': top_weight,
        'holding_count': holding_count,
        'loss_positions': loss_positions,
        'rec_symbols': list(rec_symbols),
        'followed_count': followed,
        'follow_rate': follow_rate,
    }


# ---------------- 行为分析 ----------------

def _ai_configured() -> bool:
    from ..services.settings_service import ai_key_configured
    return ai_key_configured()


def _ai_analyze(period: str, period_start: str, period_end: str, features: dict) -> dict | None:
    """DeepSeek 行为偏差分析（JSON）；无 Key / 失败返回 None（降级规则统计）"""
    if not _ai_configured():
        return None
    try:
        from ..config import settings
        from ..services.llm_client import chat
        prompt = build_review_prompt(period, period_start, period_end, features)
        text = chat([{'role': 'user', 'content': prompt}],
                    model=settings.model_chat, temperature=0.3, max_tokens=2500)
        parsed = parse_ai_output(text)
        if parsed:
            logger.info('AI 行为分析成功（%s）: %s', period, parsed.get('summary', '')[:40])
        return parsed
    except Exception as e:  # noqa: BLE001
        logger.warning('AI 行为分析失败，降级规则统计: %s', str(e)[:120])
        return None


def _rule_analyze(features: dict) -> dict:
    """规则统计行为分析（无 AI Key / AI 失败保底）：基于特征给出偏差判断与建议"""
    biases: list[dict] = []
    improvements: list[str] = []

    # 过度交易：日均交易 >= 0.5 笔
    tpd = features.get('trades_per_day', 0)
    total_trades = features.get('buy_count', 0) + features.get('sell_count', 0)
    if tpd >= 0.5:
        biases.append({
            'name': '过度交易',
            'detected': True,
            'evidence': f'区间日均交易 {tpd:.2f} 笔（共 {total_trades} 笔），频率明显偏高',
            'suggestion': '降低交易频率，减少冲动操作，按计划分批执行',
        })
        improvements.append('降低交易频率：每笔交易前先写清买卖理由，避免日内冲动操作')
    elif total_trades == 0:
        improvements.append('本区间无交易记录，可结合持仓与推荐回测数据检查是否需要调仓')
    else:
        improvements.append(f'保持当前交易节奏（日均 {tpd:.2f} 笔），继续按计划执行')

    # 处置效应：盈利平仓占比高（过早止盈）
    win = features.get('win_sells', 0)
    loss = features.get('loss_sells', 0)
    if win + loss >= 2 and win > 0 and loss / (win + loss) < 0.25:
        biases.append({
            'name': '处置效应',
            'detected': True,
            'evidence': f'区间盈利平仓 {win} 笔、亏损平仓 {loss} 笔，盈利标的过早了结',
            'suggestion': '让盈利奔跑：按目标价/移动止损持有，而非稍有浮盈即卖出',
        })
        improvements.append('避免过早止盈：盈利持仓按预设目标价或移动止损管理，不因短期波动离场')

    # 锚定效应 / 亏损持仓：浮亏持仓占比高
    loss_pos = features.get('loss_positions', 0)
    holding_count = features.get('holding_count', 0)
    if holding_count > 0 and loss_pos / holding_count >= 0.6:
        biases.append({
            'name': '锚定效应',
            'detected': True,
            'evidence': f'{holding_count} 只持仓中 {loss_pos} 只浮亏（占比 {loss_pos / holding_count * 100:.0f}%）',
            'suggestion': '锚定成本价易造成死扛：按止损纪律评估，避免以买入价作为唯一决策依据',
        })
        improvements.append('正视浮亏持仓：为每只亏损标的设定止损线，避免因锚定成本价而被动持有')

    # 持仓集中
    top = features.get('top_holding_weight', 0)
    if top >= 50:
        biases.append({
            'name': '持仓集中',
            'detected': True,
            'evidence': f'第一大持仓占组合市值 {top:.1f}%，集中度偏高',
            'suggestion': '适当分散配置，单标的风险敞口控制在组合 30% 以内',
        })
        improvements.append(f'降低集中度：第一大持仓占比 {top:.1f}%，建议分散到不同行业与市场')
    elif top >= 30:
        improvements.append(f'关注集中度：第一大持仓占比 {top:.1f}%，随行情变化及时再平衡')

    # 追涨杀跌：交易频繁 + 推荐跟随率低（自主择时特征）
    follow = features.get('follow_rate', 0)
    if total_trades >= 6 and follow < 30:
        biases.append({
            'name': '追涨杀跌',
            'detected': True,
            'evidence': f'区间交易 {total_trades} 笔较频繁，而推荐跟随率仅 {follow:.0f}%，自主追价特征明显',
            'suggestion': '结合系统推荐与回测数据决策，避免在情绪高点追入',
        })
        improvements.append(f'提高决策纪律：推荐跟随率仅 {follow:.0f}%，多参考系统推荐的回测胜率再行动')

    # 确认偏差
    if follow >= 80 and total_trades == 0:
        biases.append({
            'name': '确认偏差',
            'detected': False,
            'evidence': '当前无交易，暂未发现明显确认偏差行为',
            'suggestion': '持续记录决策理由，定期对照结果检验判断',
        })

    if not biases:
        biases.append({
            'name': '整体行为',
            'detected': False,
            'evidence': f'区间交易 {total_trades} 笔、日均 {tpd:.2f} 笔，未发现明显行为偏差',
            'suggestion': '保持现有纪律，继续按计划执行并定期复盘',
        })

    if len(improvements) < 2:
        improvements.append('坚持写交易日志：记录每笔交易的买入理由、计划止损与目标，月度回看偏差')
    if len(improvements) < 3:
        improvements.append('定期对照推荐回测报告（胜率/平均收益），验证操作是否优于系统基准')

    return {
        'summary': f'区间共 {total_trades} 笔交易（买 {features.get("buy_count", 0)} / 卖 {features.get("sell_count", 0)}），'
                   f'已实现盈亏 {features.get("realized_pnl", 0):+.2f} 元',
        'biases': biases[:6],
        'improvements': improvements[:6],
    }


# ---------------- 报告生成 ----------------

def _fmt_amount(v) -> str:
    if v is None:
        return '-'
    try:
        v = float(v)
    except (TypeError, ValueError):
        return '-'
    return f'{v:,.2f}'


def _best_worst(features: dict) -> tuple[list[dict], list[dict]]:
    """最佳/最差操作（推荐或交易按收益排序取 1-2 条）"""
    candidates: list[dict] = []
    # 推荐回测明细（recent 字段来自 backtest_service）
    bt = features.get('backtest') or {}
    for r in (bt.get('recent') or [])[:20]:
        if r.get('result_pct') is None:
            continue
        candidates.append({
            'kind': '推荐',
            'title': f'{r.get("name") or r.get("symbol")}（{r.get("symbol")}）',
            'value': float(r['result_pct']),
            'detail': f'{"短线" if r.get("rec_type") == "短线" else "长线"}推荐 结算 {r.get("result_pct"):+.2f}%'
                      f'（{"胜" if r.get("outcome") == "win" else "止损" if r.get("outcome") == "stop" else "平" if r.get("outcome") == "flat" else "亏"}）',
        })
    # 交易（已实现盈亏按金额排序）
    pnl_trades = [t for t in features.get('trades') or [] if t.get('pnl') is not None]
    for t in pnl_trades[:20]:
        name = t.get('name') or ('资产' + str(t.get('asset_id')))
        candidates.append({
            'kind': '交易',
            'title': f'{name}',
            'value': float(t['pnl']),
            'detail': f'{"买入" if t["type"] == "buy" else "卖出"} {t.get("date")} '
                      f'@ {t.get("price"):.2f} 盈亏 {t["pnl"]:+.2f} 元',
        })
    if not candidates:
        return [], []
    ranked = sorted(candidates, key=lambda c: c['value'], reverse=True)
    return ranked[:2], list(reversed(ranked[-2:]))


def _build_report(period: str, features: dict, analysis: dict, ai_used: bool) -> str:
    """四段式复盘报告：①操作盈亏汇总 ②最佳/最差 ③行为分析 ④改进建议"""
    period_cn = PERIOD_CN.get(period, '周期')
    p_start, p_end = features['period_start'], features['period_end']
    lines = [f'📋 {_local_today()} {period_cn}投资复盘（{p_start} ~ {p_end}）', '']

    # ① 操作盈亏汇总
    lines.append('## 一、操作盈亏汇总')
    holdings = features.get('holdings') or []
    total_mv = sum(h['market_value'] for h in holdings if h.get('market_value') is not None)
    total_pnl = sum(h['pnl'] for h in holdings if h.get('pnl') is not None)
    if total_pnl is None:
        pnl_line = f'**持仓**：{len(holdings)} 只，总市值 {_fmt_amount(total_mv)} 元（行情暂缺，浮动盈亏未计算）'
    else:
        cost = total_mv - total_pnl
        pct_s = f'（{total_pnl / cost * 100:+.2f}%）' if cost > 0 else ''
        pnl_line = (f'**持仓**：{len(holdings)} 只，总市值 {_fmt_amount(total_mv)} 元，'
                    f'浮动盈亏 {_fmt_amount(total_pnl)} 元{pct_s}')
    lines.append(pnl_line)
    lines.append(f'**区间交易**：买入 {features.get("buy_count", 0)} 笔 / 卖出 {features.get("sell_count", 0)} 笔，'
                 f'已实现盈亏 {_fmt_amount(features.get("realized_pnl"))} 元'
                 f'（盈利平仓 {features.get("win_sells", 0)} 笔 / 亏损平仓 {features.get("loss_sells", 0)} 笔）')
    bt = features.get('backtest') or {}
    if bt.get('count'):
        lines.append(f'**推荐回测**：{bt.get("count")} 条已结算，胜率 {bt.get("win_rate")}%，'
                     f'平均收益 {bt.get("avg_return")}%，累计收益 {bt.get("total_return")}%')
    else:
        lines.append('**推荐回测**：暂无已结算推荐（推荐将在持仓周期内自动评估）')
    nw = features.get('net_worth') or {}
    if nw.get('latest'):
        chg = nw.get('change_pct')
        chg_s = f'，较区间初 {_fmt_amount(nw.get("start"))} 元变化 {chg:+.2f}%' if chg is not None else ''
        lines.append(f'**净值**：最新 {_fmt_amount(nw.get("latest"))} 元{chg_s}')
    lines.append(f'**追踪异动**：区间内 {features.get("tracking_events", 0)} 次')
    lines.append('')

    # ② 最佳/最差操作
    lines.append('## 二、最佳 / 最差操作')
    best, worst = _best_worst(features)
    if best:
        for b in best:
            lines.append(f'- 🏆 最佳（{b["kind"]}）：{b["title"]}——{b["detail"]}')
    else:
        lines.append('- 最佳：本区间暂无已结算推荐或平仓交易')
    if worst:
        for w in worst:
            lines.append(f'- ⚠️ 最差（{w["kind"]}）：{w["title"]}——{w["detail"]}')
    else:
        lines.append('- 最差：本区间暂无已结算推荐或平仓交易')
    lines.append('')

    # ③ 行为分析
    lines.append('## 三、行为分析')
    lines.append(f'*{analysis.get("summary", "")}*')
    source = 'AI 研判' if ai_used else '规则统计'
    lines.append(f'（{source}）')
    for b in analysis.get('biases') or []:
        flag = '⚠️ 疑似' if b.get('detected') else '✅ 未见'
        lines.append(f'- {flag} {b["name"]}：{b.get("evidence", "")}'
                     + (f'；建议：{b.get("suggestion", "")}' if b.get('suggestion') else ''))
    lines.append('')

    # ④ 改进建议
    lines.append('## 四、改进建议')
    for i, s in enumerate(analysis.get('improvements') or ['保持现有交易纪律，持续记录与复盘'], 1):
        lines.append(f'{i}. {s}')
    lines.append('')
    lines.append('---')
    lines.append(f'*生成时间：{_beijing_now().strftime("%Y-%m-%d %H:%M:%S")}（{source}）*')
    lines.append(f'*{DISCLAIMER}*')
    return '\n'.join(lines)


# ---------------- 存档与查询 ----------------

REVIEW_COLS = ('id', 'period', 'period_start', 'period_end', 'content',
             'stats_json', 'behaviors_json', 'created_at')


def _row_to_review(row) -> dict:
    r = dict(row)
    try:
        r['stats'] = json.loads(r['stats_json']) if r.get('stats_json') else None
    except (ValueError, TypeError):
        r['stats'] = None
    try:
        r['behaviors'] = json.loads(r['behaviors_json']) if r.get('behaviors_json') else None
    except (ValueError, TypeError):
        r['behaviors'] = None
    r.pop('stats_json', None)
    r.pop('behaviors_json', None)
    return r


def _get_review_by_id(report_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(REVIEW_COLS)} FROM review_reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        return _row_to_review(row) if row else None
    finally:
        conn.close()


def get_latest_review() -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(REVIEW_COLS)} FROM review_reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_to_review(row) if row else None
    finally:
        conn.close()


def get_latest_review_of(period: str) -> dict | None:
    """指定周期（weekly/monthly/quarterly）的最近一份复盘报告"""
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(REVIEW_COLS)} FROM review_reports "
            "WHERE period = ? ORDER BY id DESC LIMIT 1",
            (period,),
        ).fetchone()
        return _row_to_review(row) if row else None
    finally:
        conn.close()


def list_reviews(limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(REVIEW_COLS)} FROM review_reports ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [_row_to_review(r) for r in rows]
    finally:
        conn.close()


def _save_review(period: str, period_start: str, period_end: str, content: str,
                 stats: dict | None = None, behaviors: list[dict] | None = None) -> int:
    now = utc_now()
    conn = get_connection()
    try:
        cur = conn.execute(
            'INSERT INTO review_reports (period, period_start, period_end, content, '
            'stats_json, behaviors_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (period, period_start, period_end, content,
             json.dumps(stats, ensure_ascii=False) if stats else None,
             json.dumps(behaviors, ensure_ascii=False) if behaviors else None,
             now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _notify_review(period: str, content: str) -> None:
    period_cn = PERIOD_CN.get(period, '周期')
    try:
        r = send_notification('review', f'📋 {_local_today()} {period_cn}投资复盘', content[:500],
                              level='提示', force=True)
        if not r.get('sent'):
            logger.warning('复盘通知未发送: %s', r.get('reason'))
    except Exception as e:  # noqa: BLE001
        logger.warning('复盘通知发送失败: %s', str(e)[:100])


def _stats_from_features(features: dict) -> dict:
    """结构化统计（前端契约 report.stats）"""
    bt = features.get('backtest') or {}
    nw = features.get('net_worth') or {}
    holdings = features.get('holdings') or []
    total_mv = sum(h['market_value'] for h in holdings if h.get('market_value') is not None)
    pnl_vals = [h['pnl'] for h in holdings if h.get('pnl') is not None]
    return {
        'holdings_count': len(holdings),
        'total_market_value': round(total_mv, 2),
        'total_pnl': round(sum(pnl_vals), 2) if pnl_vals else None,
        'buy_count': features.get('buy_count', 0),
        'sell_count': features.get('sell_count', 0),
        'realized_pnl': features.get('realized_pnl', 0),
        'win_sells': features.get('win_sells', 0),
        'loss_sells': features.get('loss_sells', 0),
        'backtest_count': bt.get('count', 0),
        'win_rate': bt.get('win_rate'),
        'avg_return': bt.get('avg_return'),
        'total_return': bt.get('total_return', 0),
        'tracking_events': features.get('tracking_events', 0),
        'net_worth_latest': nw.get('latest'),
        'net_worth_change_pct': nw.get('change_pct'),
    }


# ---------------- 主流程 ----------------

def generate_review(period: str = 'weekly', force: bool = False) -> dict:
    """生成周期复盘报告。period=weekly|monthly|quarterly。
    force=False 且当日同周期已生成时返回 existing（幂等，不重复存档/推送）。"""
    period = (period or 'weekly').strip().lower()
    if period not in PERIOD_DAYS:
        return {'ok': False, 'reason': f'period 参数错误: {period}（仅支持 weekly/monthly/quarterly）'}
    if _running.get(period):
        return {'ok': False, 'reason': f'{PERIOD_CN[period]}复盘正在生成中，请稍候',
                'generating': True, 'period': period, 'cached': False,
                'report': None, 'errors': []}

    period_start, period_end = _window(period)
    existing = None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM review_reports WHERE period = ? AND period_start = ? ORDER BY id DESC LIMIT 1",
            (period, period_start),
        ).fetchone()
        if row:
            existing = row['id']
    finally:
        conn.close()
    if existing and not force:
        return {'ok': True, 'period': period, 'period_start': period_start, 'period_end': period_end,
                'cached': True, 'report': _get_review_by_id(existing),
                'errors': []}

    _running[period] = True
    try:
        features = build_features(period)
        analysis = _ai_analyze(period, period_start, period_end, features)
        ai_used = analysis is not None
        if analysis is None:
            analysis = _rule_analyze(features)
        content = _build_report(period, features, analysis, ai_used)
        report_id = _save_review(period, period_start, period_end, content,
                                 _stats_from_features(features), analysis.get('biases') or [])
        _notify_review(period, content)
        logger.info('%s复盘生成完成: id=%s ai=%s 交易=%d 持仓=%d', period, report_id, ai_used,
                    features.get('buy_count', 0) + features.get('sell_count', 0),
                    features.get('holding_count', 0))
    finally:
        _running[period] = False

    return {'ok': True, 'period': period, 'period_start': period_start, 'period_end': period_end,
            'cached': False, 'report': get_latest_review(), 'ai_used': ai_used, 'errors': []}


