# -*- coding: utf-8 -*-
"""S15 投资复盘 Prompt 模板：基于周期数据特征，输出行为偏差判断（JSON 结构化）

输出要求严格 JSON（便于解析与降级）：
  {"summary": "本期操作一句话概括（≤60字）",
   "biases": [{"name": "偏差名", "detected": true/false, "evidence": "判断依据（≤60字）",
               "suggestion": "改进建议（≤50字）"}],
   "improvements": ["改进建议1", "改进建议2", ...3-5条]}
偏差候选名：追涨杀跌 / 过度交易 / 处置效应 / 确认偏差 / 锚定效应（只输出命中/疑似项，未命中可省略）
"""

import json


def _fmt_holdings(holdings: list[dict]) -> str:
    if not holdings:
        return '（无持仓数据）'
    lines = []
    for h in holdings:
        pnl = h.get('pnl')
        pnl_s = ''
        if pnl is not None:
            pnl_s = f'，浮动盈亏 {pnl:+.2f} 元'
        mv = h.get('market_value')
        mv_s = f'，市值 {mv:.2f} 元' if mv is not None else ''
        lines.append(f'{h.get("name") or h["symbol"]}（{h["symbol"]}）{h.get("market", "")} '
                     f'数量 {h.get("quantity", 0)}，成本 {h.get("cost_price", 0):.4f}'
                     f'{mv_s}{pnl_s}')
    return '；'.join(lines)


def _fmt_trades(trades: list[dict]) -> str:
    if not trades:
        return '（区间内无交易记录）'
    lines = []
    for t in trades[:20]:
        name = t.get('name') or ('资产' + str(t.get('asset_id', '')))
        pnl = t.get('pnl')
        pnl_s = f'，盈亏 {pnl:+.2f} 元' if pnl is not None else ''
        lines.append(
            f'{t.get("date", "")} {"买入" if t.get("type") == "buy" else "卖出"} {name} '
            f'{t.get("quantity", 0)} 股 @ {t.get("price", 0):.3f}{pnl_s}'
        )
    return '；'.join(lines)


def build_review_prompt(period: str, period_start: str, period_end: str, features: dict) -> str:
    """组装复盘 Prompt。features: holdings/trades/backtest/tracking/net_worth 等统计"""
    period_cn = {'weekly': '周度', 'monthly': '月度', 'quarterly': '季度'}.get(period, '周期')
    bt = features.get('backtest') or {}
    nw = features.get('net_worth') or {}
    return (
        f'你是专业的证券投资行为分析助手。请基于以下 {period_start} ~ {period_end} 的{period_cn}投资数据，'
        f'对用户的操作行为进行复盘分析。数据来自用户真实交易记录与系统统计，不要编造。\n\n'
        f'【持仓现状】\n{_fmt_holdings(features.get("holdings") or [])}\n\n'
        f'【区间交易明细】\n{_fmt_trades(features.get("trades") or [])}\n\n'
        f'【统计特征】\n'
        f'- 区间交易笔数：买入 {features.get("buy_count", 0)} 笔 / 卖出 {features.get("sell_count", 0)} 笔'
        f'（日均 {features.get("trades_per_day", 0):.2f} 笔）\n'
        f'- 已实现盈亏：{features.get("realized_pnl", 0):+.2f} 元（盈利平仓 {features.get("win_sells", 0)} 笔'
        f' / 亏损平仓 {features.get("loss_sells", 0)} 笔）\n'
        f'- 持仓集中度：第一大持仓占 {features.get("top_holding_weight", 0):.1f}%'
        f'（共 {features.get("holding_count", 0)} 只）\n'
        f'- 推荐跟随率：{features.get("follow_rate", 0):.1f}%（当前推荐 {features.get("open_rec_count", 0)} 条'
        f'，已持有其中 {features.get("followed_count", 0)} 条）\n'
        f'- 推荐回测：{bt.get("count", 0)} 条已结算，胜率 {bt.get("win_rate", 0)}%，'
        f'平均收益 {bt.get("avg_return", 0)}%，累计收益 {bt.get("total_return", 0)}%\n'
        f'- 追踪异动：区间内 {features.get("tracking_events", 0)} 次\n'
        f'- 净值：最新 {nw.get("latest", "-")} 元，区间初 {nw.get("start", "-")} 元'
        f'（变化 {nw.get("change_pct", "-")}%）\n\n'
        f'请输出严格 JSON（不要 markdown 代码块，不要多余文字），格式：\n'
        f'{{"summary": "本期操作一句话概括（≤60字）", '
        f'"biases": [{{"name": "追涨杀跌|过度交易|处置效应|确认偏差|锚定效应", '
        f'"detected": true, "evidence": "判断依据（≤60字，必须引用上面的数据）", '
        f'"suggestion": "改进建议（≤50字）"}}], '
        f'"improvements": ["改进建议1（≤50字）", ...共3-5条]}}\n'
        f'要求：只输出确有数据支撑的行为偏差；证据必须引用给定数字；改进建议具体可执行；'
        f'所有内容仅为参考，需提示风险。'
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
        start, end = t.find('{'), t.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(t[start:end + 1])
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    summary = str(data.get('summary') or '').strip()[:80]
    biases = []
    for b in (data.get('biases') or [])[:6]:
        if not isinstance(b, dict):
            continue
        name = str(b.get('name') or '').strip()[:30]
        if not name:
            continue
        biases.append({
            'name': name,
            'detected': bool(b.get('detected')),
            'evidence': str(b.get('evidence') or '').strip()[:80],
            'suggestion': str(b.get('suggestion') or '').strip()[:60],
        })
    improvements = [str(x).strip()[:80] for x in (data.get('improvements') or []) if str(x).strip()]
    if not summary and not biases:
        return None
    return {'summary': summary, 'biases': biases[:6], 'improvements': improvements[:6]}
