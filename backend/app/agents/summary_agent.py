# -*- coding: utf-8 -*-
"""S12 盘后总结 Agent：市场快照 → 持仓/追踪回顾 → AI 次日预判（失败降级规则引擎）
→ 四段式报告生成 → 存档（daily_summary）+ 推送（应用内通知）+ 情绪指标落库（market_sentiment）

报告结构（对应需求模块五）：
  ① 当日市场全景（指数/板块涨跌/资金流向/情绪指标）
  ② 持仓与追踪回顾
  ③ 次日机会预判（异动方向/潜在机会/风险预警）
  ④ 次日操作建议清单

定时（V1.0.6）：交易日 12:15 午间收盘报告（A股 11:30 / 港股 12:00 上午收盘，两市合并一次）；
16:15 全天收盘报告（两市收盘合并一次）。盘中可随时手动生成「盘中临时总结」（kind=intraday），
与收盘报告（lunch/daily）分开存储与展示，互不覆盖。
补跑：应用启动时若已过生成时刻且当日对应报告缺失则自动补生成。
"""

import json
from datetime import datetime, timezone, timedelta

from ..data_sources.market.data_fusion import data_fusion
from ..data_sources.market.snapshot_client import collect_snapshot
from ..models.database import get_connection, utc_now
from ..services.logger import get_agent_logger
from ..services.notification import send_notification
from ..utils.prompts.summary_prompt import (
    build_summary_prompt,
    parse_ai_output,
)

logger = get_agent_logger()

REPORT_MARKETS = ('A股', '港股')
COMBINED = '合并'
DISCLAIMER = '⚠️ 本报告由 AI 自动生成，仅供参考，不构成投资建议。'

# 生成中标记（前端轮询/重复触发时防并发重复生成）
_running: dict[str, bool] = {}

# V1.0.6 报告类型：lunch 午间收盘 / daily 全天收盘 / intraday 盘中临时总结
REPORT_KINDS = ('lunch', 'daily', 'intraday')
KIND_CN = {'lunch': '午间收盘报告', 'daily': '全天收盘报告', 'intraday': '盘中临时总结'}


def _local_today() -> str:
    """北京时间当日日期"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d')


def _beijing_date(iso: str) -> str | None:
    """UTC ISO -> 北京时间日期；解析失败返回 None"""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone(timedelta(hours=8)))
    return dt.strftime('%Y-%m-%d')


# ---------------- ② 持仓与追踪回顾 ----------------

def _load_holdings(markets: list[str]) -> list[dict]:
    """持仓 + 实时行情（失败跳过）：当日涨跌 / 持仓盈亏"""
    conn = get_connection()
    try:
        from ..services.portfolio_sync import get_mode
        src = 'portfolio_app' if get_mode() == 'snapshot' else 'manual'
        rows = conn.execute(
            "SELECT symbol, name, market, quantity, cost_price, current_price "
            "FROM holdings WHERE market IN (%s) AND source = ? ORDER BY market, symbol" % ','.join('?' * len(markets)),
            markets + [src],
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
            result.append({**h, 'price': None, 'change_pct': None, 'pnl_pct': None})
            continue
        price = float(q.price)
        pnl = None
        cost = float(h.get('cost_price') or 0)
        if cost > 0:
            pnl = round((price / cost - 1) * 100, 2)
        result.append({
            **h,
            'price': price,
            'change_pct': round(float(q.change_pct or 0), 2),
            'pnl_pct': pnl,
        })
    return result


def _load_tracking_review(markets: list[str]) -> dict:
    """今日追踪回顾：追踪列表 + 当日异动事件（按北京时间）"""
    from ..services.tracking_service import list_tracking
    from .tracking_agent import EVENT_TYPE_CN

    items = [t for t in list_tracking() if t['market'] in markets]
    today = _local_today()
    events_today = []
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT e.id, e.tracking_id, e.symbol, e.event_type, e.level, e.price, "
            "e.change_pct, e.detail, e.notified, e.created_at, t.name, t.market "
            "FROM tracking_events e LEFT JOIN tracking t ON t.id = e.tracking_id "
            "ORDER BY e.id DESC LIMIT 200"
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        ev = dict(row)
        if ev.get('market') not in markets:
            continue
        d = _beijing_date(ev['created_at'])
        if d != today:
            continue
        events_today.append({
            'symbol': ev['symbol'],
            'name': ev.get('name') or ev['symbol'],
            'event_type': ev['event_type'],
            'event_type_cn': EVENT_TYPE_CN.get(ev['event_type'], ev['event_type']),
            'level': ev.get('level', ''),
            'price': ev.get('price'),
            'change_pct': ev.get('change_pct'),
            'detail': (ev.get('detail') or '')[:120],
            'created_at': ev['created_at'],
        })
    return {
        'items': items,
        'events_today': events_today,
        'triggered_today': sum(int(t.get('today_triggered') or 0) for t in items),
    }


def build_review(markets: list[str]) -> dict:
    return {
        'holdings': _load_holdings(markets),
        'tracking': _load_tracking_review(markets),
    }


# ---------------- ③ 次日机会预判（AI + 规则降级） ----------------

def _ai_configured() -> bool:
    from ..services.settings_service import ai_key_configured
    return ai_key_configured()


def _ai_predict(market: str, trade_date: str, snapshot: dict, review: dict,
                    session: str = 'daily') -> dict | None:
    """DeepSeek 生成预判 JSON；无 Key/失败返回 None（降级规则引擎）。session 见 build_summary_prompt"""
    if not _ai_configured():
        return None
    try:
        from ..config import settings
        from ..services.llm_client import chat
        prompt = build_summary_prompt(market, trade_date, snapshot, review, session=session)
        text = chat([{'role': 'user', 'content': prompt}],
                    model=settings.model_chat, temperature=0.3, max_tokens=2500)
        parsed = parse_ai_output(text)
        if parsed:
            logger.info('AI 盘后预判成功（%s）: %s', market, parsed['overview'][:40])
        return parsed
    except Exception as e:  # noqa: BLE001
        logger.warning('AI 盘后预判失败，降级规则引擎: %s', str(e)[:120])
        return None


def _prev_day_sentiment(market: str, today: str) -> dict | None:
    """上一交易日情绪指标（market_sentiment），用于规则引擎对比量能/情绪"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT metric, value FROM market_sentiment "
            "WHERE market = ? AND date < ? ORDER BY date DESC, id DESC LIMIT 20",
            (market, today),
        ).fetchall()
    finally:
        conn.close()
    result: dict = {}
    for r in rows:
        result.setdefault(r['metric'], r['value'])
    return result or None


def _rule_predict(market: str, trade_date: str, snapshot: dict, review: dict,
                      session: str = 'daily') -> dict:
    """规则引擎保底预判（无 AI Key / AI 失败时使用）"""
    if session not in ('lunch', 'intraday'):
        session = 'daily'
    indices = snapshot.get('indices') or []
    breadth = snapshot.get('breadth')
    boards = snapshot.get('boards') or {}
    turnover = snapshot.get('turnover')
    holdings = review.get('holdings') or []
    events = (review.get('tracking') or {}).get('events_today') or []

    up = int((breadth or {}).get('up', 0))
    down = int((breadth or {}).get('down', 0))
    limit_up = int((breadth or {}).get('limit_up', 0))
    limit_down = int((breadth or {}).get('limit_down', 0))

    gains = [it for it in indices if it.get('change_pct', 0) > 0]
    losses = [it for it in indices if it.get('change_pct', 0) < 0]
    market_up = len(gains) >= len(losses) and len(indices) > 0
    strong = up >= down * 1.5 and up > 0
    weak = down > up * 1.5
    neutral = not strong and not weak

    prev = _prev_day_sentiment(market, trade_date)
    vol_trend = ''
    if prev and prev.get('turnover') and turnover:
        ratio = turnover / float(prev['turnover'])
        if ratio >= 1.15:
            vol_trend = f'较上一交易日放量（{ratio:.2f} 倍）'
        elif ratio <= 0.87:
            vol_trend = f'较上一交易日缩量（{ratio:.2f} 倍）'
        else:
            vol_trend = '量能与上一交易日基本持平'
    elif turnover:
        vol_trend = f'成交额 {turnover / 1e8:.0f} 亿元'

    top_gainer = (boards.get('gainers') or [{}])[0]
    top_loser = (boards.get('losers') or [{}])[0]

    outlook: list[str] = []
    if market_up:
        outlook.append(f'主要指数收涨，市场整体偏多，关注涨势能否延续（{vol_trend}）。')
    elif losses:
        outlook.append(f'主要指数收跌，短线情绪偏弱，谨防惯性下探（{vol_trend}）。')
    else:
        outlook.append(f'指数数据暂缺，建议结合明日盘面验证方向（{vol_trend}）。')
    if strong:
        outlook.append(f'上涨家数（{up}）明显多于下跌（{down}），赚钱效应较好，题材或继续活跃。')
    elif weak:
        outlook.append(f'下跌家数（{down}）明显多于上涨（{up}），亏钱效应明显，短线宜防守。')
    elif up or down:
        outlook.append(f'涨跌家数接近（涨 {up} / 跌 {down}），市场分化，结构性行情为主。')
    if top_gainer.get('name'):
        outlook.append(f'领涨板块「{top_gainer["name"]}」（+{top_gainer.get("change_pct", 0):.2f}%）次日或有惯性，注意追高风险。')
    if top_loser.get('name'):
        outlook.append(f'领跌板块「{top_loser["name"]}」（{top_loser.get("change_pct", 0):+.2f}%）存在超跌反弹可能，但不宜急于抄底。')
    if limit_up > 0:
        outlook.append(f'涨停 {limit_up} 家，短线情绪尚可；若跌停家数同步增多则需警惕分化。')
    if limit_down >= 5:
        outlook.append(f'跌停 {limit_down} 家，风险偏好回落，谨慎对待高位题材。')
    if events:
        outlook.append(f'追踪标的今日触发 {len(events)} 次异动（如 {events[0]["name"]} {events[0]["event_type_cn"]}），次日重点观察其走势确认。')
    if not outlook:
        outlook.append('数据源暂不可用，建议明日开盘后结合实时行情再作判断。')

    suggestions: list[dict] = []
    best = max(holdings, key=lambda h: h.get('pnl_pct') or -999, default=None) if holdings else None
    worst = min(holdings, key=lambda h: h.get('pnl_pct') or 999, default=None) if holdings else None
    if best and (best.get('pnl_pct') or 0) >= 5:
        suggestions.append({'action': '止盈保护', 'target': f'{best["name"]}（{best["symbol"]}）',
                            'reason': f'持仓浮盈 {best["pnl_pct"]:+.1f}%，可分批止盈锁定收益', 'risk': '过早离场可能踏空'})
    if worst and (worst.get('pnl_pct') or 0) <= -5:
        suggestions.append({'action': '设好止损', 'target': f'{worst["name"]}（{worst["symbol"]}）',
                            'reason': f'持仓浮亏 {worst["pnl_pct"]:+.1f}%，严格执行止损纪律', 'risk': '止损过近易被洗出'})
    if top_gainer.get('name'):
        suggestions.append({'action': '观察确认', 'target': f'板块「{top_gainer["name"]}」',
                            'reason': '领涨板块次日若高开回落不追，回踩企稳再评估', 'risk': '追高买入易被套'})
    if top_loser.get('name'):
        suggestions.append({'action': '暂不抄底', 'target': f'板块「{top_loser["name"]}」',
                            'reason': '领跌板块趋势未明，等待止跌信号', 'risk': '左侧抄底可能继续下跌'})
    if weak:
        suggestions.append({'action': '控制仓位', 'target': '整体仓位',
                            'reason': '市场下跌家数占优，短线降低仓位、减少交易频率', 'risk': '踏空反弹'})
    if events:
        suggestions.append({'action': '重点跟踪', 'target': f'{events[0]["name"]}（{events[0]["symbol"]}）',
                            'reason': '今日异动标的需要次日确认方向（延续或反转）', 'risk': '异动后波动加大'})
    if not suggestions:
        suggestions.append({'action': '观望为主', 'target': '整体仓位',
                            'reason': '数据不足或市场平淡，先观察再决策', 'risk': '机会成本'})

    overview = ''
    if indices and (up or down):
        avg = sum(i.get('change_pct', 0) for i in indices) / len(indices)
        tone = '偏暖' if avg > 0.3 else ('偏弱' if avg < -0.3 else '震荡')
        overview = f'主要指数平均涨跌 {avg:+.2f}%，上涨 {up} / 下跌 {down} 家，市场情绪{tone}。'
    elif indices:
        overview = f'主要指数平均涨跌 {sum(i.get("change_pct", 0) for i in indices) / len(indices):+.2f}%。'
    else:
        overview = '当日行情数据暂不可用，报告基于已有信息生成。'

    result = {'overview': overview, 'outlook': outlook, 'suggestions': suggestions}
    if session != 'daily':
        # 午间/盘中语境：把"次日/明日/收涨/收跌"等收盘措辞本地化
        rep = {'次日': '接下来', '明日': '接下来', '明日开盘后': '午后开盘后',
               '收涨': '上涨', '收跌': '下跌', '开盘后': '午后'}
        for key in ('overview', 'outlook', 'suggestions'):
            val = result[key]
            if key == 'suggestions':
                for s in val:
                    s['reason'] = _rep_all(s.get('reason', ''), rep)
                    s['risk'] = _rep_all(s.get('risk', ''), rep)
                    s['action'] = _rep_all(s.get('action', ''), rep)
            elif isinstance(val, list):
                result[key] = [_rep_all(str(x), rep) for x in val]
            else:
                result[key] = _rep_all(str(val), rep)
    return result


def _rep_all(text: str, rep: dict) -> str:
    """按顺序做整词替换（长词优先）"""
    for k in sorted(rep, key=len, reverse=True):
        text = text.replace(k, rep[k])
    return text


# ---------------- 四段式报告生成 ----------------

def _fmt_amt(v: float | None) -> str:
    if not v:
        return '-'
    yi = v / 1e8
    return f'{yi / 10000:.2f} 万亿' if yi >= 10000 else f'{yi:.0f} 亿元'


def _fmt_board_line(b: dict) -> str:
    inflow = b.get('main_inflow') or 0
    s = f'{b["name"]} {b["change_pct"]:+.2f}%'
    if inflow:
        s += f'（主力净流入 {inflow / 1e8:.1f} 亿）' if inflow > 0 else f'（主力净流出 {abs(inflow) / 1e8:.1f} 亿）'
    return s


def build_report(market: str, trade_date: str, snapshot: dict, review: dict,
                 prediction: dict, ai_used: bool, session: str = 'daily',
                 title: str | None = None) -> str:
    """四段式 Markdown 报告。session: daily/lunch/intraday（决定小节措辞与数据窗口说明）"""
    market_cn = {'A股': 'A股盘后总结', '港股': '港股盘后总结', '合并': '全市场报告'}[market]
    head = title or f'📊 {trade_date} {market_cn}'
    lines = [head, '']
    session_note = {
        'daily': '数据窗口：全天收盘（A股 15:00 / 港股 16:00 收盘）',
        'lunch': '数据窗口：上午收盘（A股 11:30 / 港股 12:00 收盘）',
        'intraday': '数据窗口：今日开盘至现在的实时行情',
    }.get(session, '')

    if session_note:
        lines.append(f'*{session_note}*')
        lines.append('')

    # ① 当日市场全景
    lines.append('## 一、当日市场全景')
    indices = snapshot.get('indices') or []
    if indices:
        lines.append('**指数**：' + '｜'.join(
            f'{it["name"]} {it["price"]:.2f}（{it["change_pct"]:+.2f}%）' for it in indices))
    boards = snapshot.get('boards')
    if boards:
        gainers = (boards.get('gainers') or [])[:5]
        losers = (boards.get('losers') or [])[:5]
        if gainers:
            lines.append('**领涨板块**：' + '；'.join(_fmt_board_line(b) for b in gainers))
        if losers:
            lines.append('**领跌板块**：' + '；'.join(_fmt_board_line(b) for b in losers))
    breadth = snapshot.get('breadth')
    turnover = snapshot.get('turnover')
    if breadth:
        lines.append(f'**资金与情绪**：两市成交额 {_fmt_amt(breadth.get("turnover") or turnover)}；'
                     f'上涨 {breadth.get("up", 0)} 家 / 下跌 {breadth.get("down", 0)} 家 / '
                     f'平盘 {breadth.get("flat", 0)} 家；涨停 {breadth.get("limit_up", 0)} / '
                     f'跌停 {breadth.get("limit_down", 0)}')
    elif turnover:
        lines.append(f'**资金**：成交额 {_fmt_amt(turnover)}（情绪家数数据源未提供）')
    else:
        lines.append('**市场数据**：数据源暂不可用')
    lines.append('')

    # ② 持仓与追踪回顾
    lines.append('## 二、持仓与追踪回顾')
    holdings = review.get('holdings') or []
    if holdings:
        lines.append(f'**持仓（{len(holdings)} 只）**：')
        for h in holdings:
            if h.get('price') is None:
                lines.append(f'- {h["name"]}（{h["symbol"]}）：行情获取失败')
                continue
            pnl = h.get('pnl_pct')
            pnl_s = f'，持仓盈亏 {pnl:+.2f}%' if pnl is not None else ''
            lines.append(f'- {h["name"]}（{h["symbol"]}）现价 {h["price"]:.2f}'
                         f'（当日 {h.get("change_pct", 0):+.2f}%）{pnl_s}')
    else:
        lines.append('**持仓**：（无持仓数据）')
    tracking = review.get('tracking') or {}
    lines.append(f'**追踪（{len(tracking.get("items") or [])} 只，今日触发 {tracking.get("triggered_today", 0)} 次）**：')
    events = tracking.get('events_today') or []
    if events:
        for ev in events[:10]:
            detail = ev.get('detail') or ''
            extra = f'——{detail}' if detail else ''
            lines.append(f'- {ev["name"]}：{ev["event_type_cn"]}（{ev.get("level", "")}）{extra}')
    else:
        lines.append('- 今日无触发异动事件')
    lines.append('')

    # ③ 走势研判/关注要点
    sec3 = {'lunch': '三、下午走势研判', 'intraday': '三、后续关注要点'}.get(session, '三、次日机会预判')
    lines.append(f'## {sec3}')
    lines.append(f'*{prediction.get("overview", "")}*')
    for i, o in enumerate(prediction.get('outlook') or [], 1):
        lines.append(f'{i}. {o}')
    lines.append('')

    # ④ 操作建议清单
    sec4 = {'lunch': '四、下午操作建议清单', 'intraday': '四、接下来的操作建议'}.get(session, '四、次日操作建议清单')
    lines.append(f'## {sec4}')
    for i, s in enumerate(prediction.get('suggestions') or [], 1):
        parts = [s.get('action', '')]
        if s.get('target'):
            parts.append(f'标的：{s["target"]}')
        if s.get('reason'):
            parts.append(f'理由：{s["reason"]}')
        if s.get('risk'):
            parts.append(f'风险：{s["risk"]}')
        lines.append(f'{i}. ' + '；'.join(parts))
    lines.append('')
    source = 'AI 研判' if ai_used else '规则引擎'
    lines.append(f'---')
    lines.append(f'*生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}（{source}）*')
    lines.append(f'*{DISCLAIMER}*')
    return '\n'.join(lines)


# ---------------- 情绪指标落库（market_sentiment） ----------------

def _persist_sentiment(market: str, trade_date: str, snapshot: dict) -> None:
    """快照关键指标写入 market_sentiment（按 market+date 幂等覆盖）"""
    metrics: dict[str, float] = {}
    breadth = snapshot.get('breadth')
    turnover = snapshot.get('turnover')
    if breadth:
        metrics.update({
            'turnover': breadth.get('turnover') or 0,
            'up_count': breadth.get('up', 0),
            'down_count': breadth.get('down', 0),
            'flat_count': breadth.get('flat', 0),
            'limit_up': breadth.get('limit_up', 0),
            'limit_down': breadth.get('limit_down', 0),
        })
        boards = snapshot.get('boards') or {}
        gainers = boards.get('gainers') or []
        losers = boards.get('losers') or []
        if gainers:
            metrics['board_top_gain'] = gainers[0].get('change_pct') or 0
            metrics['board_top_inflow'] = gainers[0].get('main_inflow') or 0
        if losers:
            metrics['board_top_loss'] = losers[0].get('change_pct') or 0
    elif turnover:
        metrics['turnover'] = turnover
    indices = snapshot.get('indices') or []
    if indices:
        metrics['index_avg_chg'] = round(sum(i.get('change_pct', 0) for i in indices) / len(indices), 4)
    if not metrics:
        return
    now = utc_now()
    conn = get_connection()
    try:
        conn.execute('DELETE FROM market_sentiment WHERE market = ? AND date = ?', (market, trade_date))
        for metric, value in metrics.items():
            conn.execute(
                'INSERT INTO market_sentiment (market, date, metric, value, created_at) VALUES (?, ?, ?, ?, ?)',
                (market, trade_date, metric, round(float(value), 4), now),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------- 存档与查询 ----------------

SUMMARY_COLS = ('id', 'trade_date', 'market', 'report_type', 'title', 'content', 'suggestions',
                'snapshot_json', 'ai_used', 'generated_at', 'created_at', 'kind')


def _norm_kind(k) -> str:
    """报告类型归一：旧记录（kind 为 NULL）按 daily（全天收盘）处理"""
    return str(k or 'daily') if str(k or 'daily') in REPORT_KINDS else 'daily'


def _row_to_report(row) -> dict:
    r = dict(row)
    # suggestions 保持原始 JSON 字符串（前端契约：字符串形式，可自行解析）
    r['suggestions'] = r.get('suggestions') or ''
    try:
        r['snapshot'] = json.loads(r['snapshot_json']) if r.get('snapshot_json') else None
    except (ValueError, TypeError):
        r['snapshot'] = None
    r.pop('snapshot_json', None)
    r['ai_used'] = bool(r.get('ai_used'))
    r['kind'] = _norm_kind(r.get('kind'))
    # 兼容旧前端：report_type 保持旧语义（市场名/合并日报）
    if 'report_type' in r and r.get('kind'):
        r['report_type'] = r.get('report_type') or (r['market'] if r['market'] != COMBINED else '合并日报')
    return r


def get_today_summary(market: str, kind: str | None = None) -> dict | None:
    """当日指定市场报告（kind=None 取当日最新任意类型；kind 指定类型时 NULL 旧记录视为 daily）"""
    conn = get_connection()
    try:
        if kind is None:
            row = conn.execute(
                f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary "
                "WHERE trade_date = ? AND market = ? ORDER BY id DESC LIMIT 1",
                (_local_today(), market),
            ).fetchone()
        elif kind == 'daily':
            row = conn.execute(
                f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary "
                "WHERE trade_date = ? AND market = ? AND (kind = 'daily' OR kind IS NULL) "
                "ORDER BY id DESC LIMIT 1",
                (_local_today(), market),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary "
                "WHERE trade_date = ? AND market = ? AND kind = ? ORDER BY id DESC LIMIT 1",
                (_local_today(), market, kind),
            ).fetchone()
        return _row_to_report(row) if row else None
    finally:
        conn.close()


def get_today_report(kind: str) -> dict | None:
    """当日指定类型报告（合并两市口径；lunch/daily/intraday）"""
    return get_today_summary(COMBINED, kind)


def list_today_reports() -> list[dict]:
    """当日全部报告（任意市场/类型，按时间排序），供今日区展示"""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary "
            "WHERE trade_date = ? ORDER BY id",
            (_local_today(),),
        ).fetchall()
        return [_row_to_report(r) for r in rows]
    finally:
        conn.close()


def list_summaries(limit: int = 30) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary ORDER BY trade_date DESC, id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [_row_to_report(r) for r in rows]
    finally:
        conn.close()


def today_reports(auto_generate: bool = True) -> list[dict]:
    """今日全部报告（任意市场/类型，含 lunch/daily/intraday）。auto_generate=True 时：
    交易日且已过 12:15 未生成午间报告 → 自动补午间；已过 16:15 未生成全天报告 → 自动补全天。"""
    from ..services.trading_calendar import is_trading_day

    result = list_today_reports()
    if not auto_generate or not is_trading_day('A股'):
        return result
    now = datetime.now()
    t = now.hour * 60 + now.minute
    try:
        def _merged_done(kind: str) -> bool:
            return any(r.get('kind') == kind and r.get('market') == COMBINED for r in result)

        if t >= 12 * 60 + 15 and not _merged_done('lunch'):
            gen = generate_period_report('lunch', force=False)
            if gen.get('ok') and not gen.get('cached'):
                logger.info('今日区自动补生成：午间收盘报告')
        if t >= 16 * 60 + 15 and not _merged_done('daily'):
            gen = generate_period_report('daily', force=False)
            if gen.get('ok') and not gen.get('cached'):
                logger.info('今日区自动补生成：全天收盘报告')
    except Exception as e:  # noqa: BLE001
        logger.warning('today_reports 自动补报告失败: %s', str(e)[:100])
    return list_today_reports()


def get_latest_report() -> dict | None:
    """最新报告（优先当日「全天收盘报告」，其次当日午间/盘中，最后任意历史最新）"""
    today = _local_today()
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary "
            "WHERE trade_date = ? AND market = ? AND (kind = 'daily' OR kind IS NULL) "
            "ORDER BY id DESC LIMIT 1",
            (today, COMBINED),
        ).fetchone()
        if row is None:
            row = conn.execute(
                f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary "
                "WHERE trade_date = ? AND market = ? ORDER BY id DESC LIMIT 1",
                (today, COMBINED),
            ).fetchone()
        if row is None:
            row = conn.execute(
                f"SELECT {', '.join(SUMMARY_COLS)} FROM daily_summary ORDER BY trade_date DESC, id DESC LIMIT 1"
            ).fetchone()
        return _row_to_report(row) if row else None
    finally:
        conn.close()


def _save_summary(market: str, trade_date: str, title: str, content: str,
                  suggestions: list[dict], snapshot: dict, ai_used: bool,
                  kind: str = 'daily') -> int:
    """存档报告：kind ∈ lunch/daily/intraday；同(日期,市场,类型)覆盖（盘中总结同样当日覆盖最新一条）"""
    now = utc_now()
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM daily_summary WHERE trade_date = ? AND market = ? AND (kind = ? OR (kind IS NULL AND ? = 'daily'))",
            (trade_date, market, kind, kind),
        )
        cur = conn.execute(
            '''INSERT INTO daily_summary
            (trade_date, market, content, suggestions, report_type, title, snapshot_json, ai_used, generated_at, created_at, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (trade_date, market, content,
             json.dumps(suggestions, ensure_ascii=False),
             kind,
             title,
             json.dumps(snapshot, ensure_ascii=False, default=str),
             1 if ai_used else 0, now, now, kind),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _notify_summary(market: str, title: str, content: str) -> None:
    """推送应用内通知（盘后总结类型，force 跳过冷却与免打扰）"""
    preview = content[:500]
    try:
        r = send_notification('summary', title, preview, level='提示', force=True)
        if not r.get('sent'):
            logger.warning('盘后总结通知未发送: %s', r.get('reason'))
    except Exception as e:  # noqa: BLE001
        logger.warning('盘后总结通知发送失败: %s', str(e)[:100])


# ---------------- 主流程：合并两市收盘报告（午间/全天/盘中临时） ----------------

def generate_period_report(kind: str, force: bool = False) -> dict:
    """合并 A股+港股 生成报告（V1.0.6 主入口）：
    - lunch   12:15 午间收盘报告（A股 11:30 / 港股 12:00 已收盘）
    - daily   16:15 全天收盘报告（两市均已收盘）
    - intraday 盘中随时临时总结（今日开盘至现在的实时数据，手动触发）
    force=False 且当日同类型已生成时返回缓存（覆盖当日最新一条）。"""
    if kind not in REPORT_KINDS:
        return {'ok': False, 'reason': f'kind 参数错误: {kind}（可选 lunch/daily/intraday）'}
    lock_key = f'{COMBINED}:{kind}'
    trade_date = _local_today()
    if _running.get(lock_key):
        return {'ok': False, 'reason': f'{KIND_CN[kind]}正在生成中，请稍候', 'generating': True,
                'date': trade_date, 'market': COMBINED, 'kind': kind, 'cached': False,
                'report': None, 'errors': []}
    existing = get_today_report(kind)
    if existing and not force:
        return {'ok': True, 'date': trade_date, 'market': COMBINED, 'kind': kind, 'cached': True,
                'report': existing, 'errors': []}

    _running[lock_key] = True
    try:
        # 实时采集两市快照（各时段数据窗口由行情源返回当前最新值）
        snap_a = collect_snapshot('A股')
        snap_h = collect_snapshot('港股')
        snapshot = {
            'market': COMBINED,
            'indices': (snap_a.get('indices') or []) + (snap_h.get('indices') or []),
            'breadth': snap_a.get('breadth'),
            'boards': snap_a.get('boards'),
            'turnover': ((snap_a.get('turnover') or 0) + (snap_h.get('turnover') or 0)) or None,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        review = build_review(['A股', '港股'])
        prediction = _ai_predict(COMBINED, trade_date, snapshot, review, session=kind)
        ai_used = prediction is not None
        if prediction is None:
            prediction = _rule_predict(COMBINED, trade_date, snapshot, review, session=kind)
        title = _period_title(kind, trade_date)
        content = build_report(COMBINED, trade_date, snapshot, review, prediction, ai_used,
                               session=kind, title=title)
        report_id = _save_summary(COMBINED, trade_date, title, content,
                                  prediction.get('suggestions') or [], snapshot, ai_used, kind=kind)
        _notify_summary(COMBINED, title, content)
        logger.info('%s 生成完成: id=%s ai=%s 指数=%d 板块=%s',
                    KIND_CN[kind], report_id, ai_used, len(snapshot.get('indices') or []),
                    'Y' if snapshot.get('boards') else 'N')
    finally:
        _running[lock_key] = False

    return {'ok': True, 'date': trade_date, 'market': COMBINED, 'kind': kind, 'cached': False,
            'report': get_today_report(kind), 'ai_used': ai_used, 'errors': []}


def _period_title(kind: str, trade_date: str) -> str:
    """按类型生成标题（盘中总结标题带生成时刻）"""
    if kind == 'intraday':
        return f'📊 {trade_date} 盘中临时总结（截至 {datetime.now().strftime("%H:%M")}）'
    return f'📊 {trade_date} {KIND_CN[kind]}（A股+港股）'


# ---------------- 主流程：单市场总结（兼容旧入口） / 合并日报 ----------------

def generate_market_summary(market: str = 'A股', force: bool = False) -> dict:
    """生成单市场盘后总结（A股/港股）。force=False 且当日已生成时返回缓存。"""
    if market not in REPORT_MARKETS:
        return {'ok': False, 'reason': f'market 参数错误: {market}（仅支持 A股/港股）'}
    if _running.get(market):
        return {'ok': False, 'reason': f'{market} 报告正在生成中，请稍候', 'generating': True,
                'date': _local_today(), 'market': market, 'cached': False,
                'report': None, 'errors': []}
    trade_date = _local_today()
    existing = get_today_summary(market)
    if existing and not force:
        return {'ok': True, 'date': trade_date, 'market': market, 'cached': True,
                'report': existing, 'errors': []}

    _running[market] = True
    try:
        snapshot = collect_snapshot(market)
        review = build_review([market])

        prediction = _ai_predict(market, trade_date, snapshot, review)
        ai_used = prediction is not None
        if prediction is None:
            prediction = _rule_predict(market, trade_date, snapshot, review)

        title = f'📊 {trade_date} {"A股" if market == "A股" else "港股"}盘后总结'
        content = build_report(market, trade_date, snapshot, review, prediction, ai_used)
        report_id = _save_summary(market, trade_date, title, content,
                                  prediction.get('suggestions') or [], snapshot, ai_used)
        _persist_sentiment(market, trade_date, snapshot)
        _notify_summary(market, title, content)
        logger.info('%s 盘后总结生成完成: id=%s ai=%s 指数=%d 板块=%s',
                    market, report_id, ai_used, len(snapshot.get('indices') or []),
                    'Y' if snapshot.get('boards') else 'N')
    finally:
        _running[market] = False

    return {'ok': True, 'date': trade_date, 'market': market, 'cached': False,
            'report': get_today_summary(market), 'ai_used': ai_used, 'errors': []}


def generate_combined_report(force: bool = False) -> dict:
    """合并全市场收盘报告（旧 17:30 日报入口，V1.0.6 起统一走 generate_period_report('daily')）"""
    return generate_period_report('daily', force=force)


# ---------------- 定时与补跑 ----------------

def register_summary_jobs() -> None:
    """注册收盘报告定时任务（V1.0.6）：交易日 12:15 午间收盘报告 / 16:15 全天收盘报告（A股+港股一次合并）"""
    from ..services.scheduler import add_cron_job
    from ..services.trading_calendar import is_trading_day

    def _mk_job(kind: str) -> None:
        def job() -> None:
            if not is_trading_day('A股'):
                return
            try:
                generate_period_report(kind, force=False)
            except Exception as e:  # noqa: BLE001
                logger.error('定时 %s 生成失败: %s', KIND_CN[kind], e)
        add_cron_job(job, hour=12 if kind == 'lunch' else 16,
                     minute=15, job_id='summary_' + kind)

    _mk_job('lunch')
    _mk_job('daily')
    logger.info('收盘报告定时任务已注册（交易日 12:15 午间 / 16:15 全天，A股+港股合并，仅交易日）')


def catchup_summaries() -> None:
    """开机补跑（V1.0.6）：交易日且已过 12:15/16:15 而当日对应报告缺失时自动补生成"""
    from ..services.trading_calendar import is_trading_day
    if not is_trading_day('A股'):
        return
    now = datetime.now()
    t = now.hour * 60 + now.minute
    today_rows = list_today_reports()

    def _done(kind: str) -> bool:
        return any(r.get('kind') == kind and r.get('market') == COMBINED for r in today_rows)

    if t >= 12 * 60 + 15 and not _done('lunch'):
        try:
            r = generate_period_report('lunch', force=False)
            if not r.get('cached') and r.get('ok'):
                logger.info('开机补跑：午间收盘报告已生成')
        except Exception as e:  # noqa: BLE001
            logger.error('补跑 午间收盘报告失败: %s', e)
    if t >= 16 * 60 + 15 and not _done('daily'):
        try:
            r = generate_period_report('daily', force=False)
            if not r.get('cached') and r.get('ok'):
                logger.info('开机补跑：全天收盘报告已生成')
        except Exception as e:  # noqa: BLE001
            logger.error('补跑 全天收盘报告失败: %s', e)
