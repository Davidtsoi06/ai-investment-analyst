# -*- coding: utf-8 -*-
"""S12 盘后总结 Prompt 模板：四段式报告（当日市场全景 / 持仓与追踪回顾 / 次日机会预判 / 次日操作建议清单）

输出要求 JSON 结构化（便于解析与降级）：
  {"overview": "当日市场一句话概括（≤60字）",
   "outlook": ["次日预判要点1（方向/机会/风险）", ...3-5条],
   "suggestions": [{"action": "操作动作", "target": "标的/范围", "reason": "理由", "risk": "风险提示"}, ...3-6条]}
"""

import json


def _fmt_amount(v: float | None) -> str:
    """元 -> 亿/万亿 可读格式；None/0 -> '-'"""
    if not v:
        return '-'
    yi = v / 1e8
    if yi >= 10000:
        return f'{yi / 10000:.2f} 万亿'
    return f'{yi:.0f} 亿'


def _fmt_indices(indices: list[dict]) -> str:
    if not indices:
        return '（指数数据暂不可用）'
    return '；'.join(
        f'{it["name"]} {it["price"]:.2f}（{it["change_pct"]:+.2f}%）'
        for it in indices
    )


def _fmt_boards(boards: dict | None, top: int = 3) -> str:
    if not boards:
        return '（板块数据暂不可用）'
    parts: list[str] = []
    for label, key in (('领涨', 'gainers'), ('领跌', 'losers')):
        rows = (boards.get(key) or [])[:top]
        if rows:
            parts.append(label + '：' + '、'.join(
                f'{b["name"]} {b["change_pct"]:+.2f}%' for b in rows
            ))
        else:
            parts.append(label + '：无数据')
    return '；'.join(parts)


def _fmt_breadth(breadth: dict | None, turnover: float | None) -> str:
    if not breadth:
        return f'成交额 {_fmt_amount(turnover)}' if turnover else '（情绪数据暂不可用）'
    return (
        f'两市成交额 {_fmt_amount(breadth.get("turnover") or turnover)}；'
        f'上涨 {breadth.get("up", 0)} 家 / 下跌 {breadth.get("down", 0)} 家 / '
        f'平盘 {breadth.get("flat", 0)} 家；涨停 {breadth.get("limit_up", 0)} / 跌停 {breadth.get("limit_down", 0)}'
    )


def _fmt_holdings(holdings: list[dict]) -> str:
    if not holdings:
        return '（无持仓数据）'
    lines = []
    for h in holdings:
        pnl = h.get('pnl_pct')
        pnl_s = f'当日 {h.get("change_pct", 0):+.2f}%' if h.get('change_pct') is not None else '当日行情获取失败'
        if pnl is not None:
            pnl_s += f'，持仓盈亏 {pnl:+.2f}%'
        lines.append(f'{h["name"]}（{h["symbol"]}）现价 {h.get("price", "-")}，{pnl_s}')
    return '；'.join(lines)


def _fmt_tracking(tracking: dict) -> str:
    if not tracking:
        return '（无追踪股票）'
    parts = [f'共 {len(tracking["items"])} 只追踪，今日触发 {tracking["triggered_today"]} 次']
    for ev in tracking.get('events_today') or []:
        parts.append(f'{ev["name"] or ev["symbol"]}：{ev["event_type_cn"]}（{ev.get("level", "")}）')
    return '；'.join(parts)


def build_snapshot_text(market: str, snapshot: dict) -> str:
    """把快照压缩为 Prompt 上下文文本"""
    parts = [
        f'指数：{_fmt_indices(snapshot.get("indices") or [])}',
        f'板块：{_fmt_boards(snapshot.get("boards"))}',
        f'资金与情绪：{_fmt_breadth(snapshot.get("breadth"), snapshot.get("turnover"))}',
    ]
    return '\n'.join(parts)


def build_review_text(review: dict) -> str:
    parts = [
        f'持仓：{_fmt_holdings(review.get("holdings") or [])}',
        f'追踪：{_fmt_tracking(review.get("tracking") or {})}',
    ]
    return '\n'.join(parts)


SESSION_TEXT = {
    # daily：全天收盘（16:15）→ 次日预判（原版语义）
    'daily': {
        'head': '生成次日投资预判与操作建议',
        'static': '这是收盘后的静态数据，不要假设盘中实时变化；',
        'outlook_desc': '次日预判要点（每条约40字：方向/潜在机会/风险预警，3-5条）',
        'note': '预判必须基于给定数据推导，禁止凭空推荐个股。',
    },
    # lunch：午间收盘（12:15，A股 11:30 / 港股 12:00 收盘）→ 下午盘研判
    'lunch': {
        'head': '生成今日下午盘走势研判与操作建议',
        'static': '这是上午收盘（午间）的静态数据（A股 11:30、港股 12:00 已收盘），不要假设午后实时变化；',
        'outlook_desc': '下午走势研判要点（每条约40字：午后方向/潜在机会/风险预警，3-5条）',
        'note': '研判必须基于上午收盘数据推导，禁止凭空推荐个股。',
    },
    # intraday：盘中随时临时总结（开盘至今）→ 现状总结 + 后续关注
    'intraday': {
        'head': '生成一份今日盘中投资总结（市场现状 + 持仓表现 + 接下来的关注要点与操作注意）',
        'static': '这是今日开盘至今的实时/最新数据，行情随时可能变化；',
        'outlook_desc': '后续关注要点（每条约40字：方向/潜在机会/风险预警，3-5条）',
        'note': '总结必须基于给定数据推导，禁止凭空推荐个股。',
    },
}


def build_summary_prompt(market: str, trade_date: str, snapshot: dict, review: dict,
                         session: str = 'daily') -> str:
    """盘后总结 Prompt（输出严格 JSON）。session: daily（全天收盘）/ lunch（午间）/ intraday（盘中）"""
    market_cn = 'A股' if market == 'A股' else ('港股' if market == '港股' else 'A股+港股全市场')
    txt = SESSION_TEXT.get(session, SESSION_TEXT['daily'])
    return (
        f'你是专业严谨的证券投资分析助手。请基于以下 {trade_date} 日{market_cn}'
        f'{"盘后" if session == "daily" else ("午间收盘" if session == "lunch" else "盘中实时")}数据，'
        f'{txt["head"]}\n'
        f'注意：{txt["static"]}保持客观，不要编造数据；'
        f'所有建议仅为参考，需提示风险。\n\n'
        f'【当日市场全景】\n{build_snapshot_text(market, snapshot)}\n\n'
        f'【持仓与追踪回顾】\n{build_review_text(review)}\n\n'
        f'请输出严格 JSON（不要 markdown 代码块，不要多余文字），格式：\n'
        f'{{"overview": "市场一句话概括（≤60字）", '
        f'"outlook": ["{txt["outlook_desc"]}"], '
        f'"suggestions": [{{"action": "操作动作", "target": "标的/范围", "reason": "理由（≤40字）", '
        f'"risk": "风险提示（≤30字）"}}]（3-6条）}}\n'
        f'{txt["note"]}'
    )


def parse_ai_output(text: str) -> dict | None:
    """解析 AI 返回的 JSON（容错 markdown 围栏）；非法返回 None"""
    if not text:
        return None
    t = text.strip()
    fence = chr(96) * 3
    if t.startswith(fence):
        lines = t.split('\n')
        if lines and lines[0].strip() == fence:
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        t = '\n'.join(lines).strip()
    try:
        data = json.loads(t)
    except (ValueError, TypeError):
        # 尝试截取第一个 { 到最后一个 }
        start, end = t.find('{'), t.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(t[start:end + 1])
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    overview = str(data.get('overview') or '').strip()[:80]
    outlook = [str(x).strip()[:100] for x in (data.get('outlook') or []) if str(x).strip()]
    sugg = []
    for s in (data.get('suggestions') or [])[:8]:
        if not isinstance(s, dict):
            continue
        action = str(s.get('action') or '').strip()[:60]
        if not action:
            continue
        sugg.append({
            'action': action,
            'target': str(s.get('target') or '').strip()[:60],
            'reason': str(s.get('reason') or '').strip()[:80],
            'risk': str(s.get('risk') or '').strip()[:60],
        })
    if not overview and not outlook:
        return None
    if not outlook and not sugg:
        return None
    return {'overview': overview, 'outlook': outlook[:6], 'suggestions': sugg[:8]}
