# -*- coding: utf-8 -*-
"""V1.1.1 M3 一键诊股：聚合行情/K线/技术指标/高低位/资金/资讯/研报 + AI 综合点评"""

import json

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection
from ..services.indicators import indicator_snapshot
from ..utils.prompts.research_prompt import build_interpret_prompt  # noqa: F401 复用不必要, 占位删除
from .logger import get_agent_logger

logger = get_agent_logger()

DISCLAIMER = '本分析由 AI 基于公开行情与资讯自动生成，仅供参考，不构成任何投资建议。'


def _position_label(closes: list[float], rsi) -> str:
    low = min(closes[-60:]) if len(closes) >= 20 else min(closes)
    high = max(closes[-60:]) if len(closes) >= 20 else max(closes)
    if high <= low:
        return '中位'
    pct = (closes[-1] - low) / (high - low)
    if pct > 0.75 or (rsi is not None and float(rsi) > 70):
        return '高位'
    if pct < 0.25 or (rsi is not None and float(rsi) < 30):
        return '低位'
    return '中位'


def _related_news(symbol: str, name: str, limit: int = 3) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT title, source, level, summary, published_at, url FROM news_cache "
            "WHERE title LIKE ? OR title LIKE ? OR summary LIKE ? OR summary LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (f'%{name}%', f'%{symbol}%', f'%{name}%', f'%{symbol}%', limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _research_items(symbol: str, name: str, limit: int = 3) -> list[dict]:
    """研报列表（关键词匹配；复用东财研报源，失败静默）"""
    try:
        from ..data_sources.research.eastmoney_research import list_research
        kw = symbol if symbol else name
        items = list_research(keyword=kw, limit=limit)
        return (items if isinstance(items, list) else [])[:limit]
    except Exception as e:  # noqa: BLE001
        logger.warning('诊股研报查询失败: %s', str(e)[:100])
        return []


def analyze_stock(symbol: str, market: str) -> dict:
    """聚合分析；{ok, symbol, name, market, quote, kline, tech, position, news, research, disclaimer}"""
    q = data_fusion.get_quote(symbol, market)
    if q is None:
        return {'ok': False, 'error': f'行情获取失败（{symbol}），请检查代码或稍后重试'}
    bars = data_fusion.get_kline(symbol, market, 120)
    if not bars:
        return {'ok': False, 'error': f'K线获取失败（{symbol}），请稍后重试'}
    snap = indicator_snapshot(bars) or {}
    closes = [float(b.close) for b in bars]
    tech = {
        'date': snap.get('date'), 'close': snap.get('close'),
        'ma_status': snap.get('ma_status'),
        'macd': {'dif': snap.get('dif'), 'dea': snap.get('dea'), 'hist': snap.get('hist'),
                 'golden_cross': snap.get('macd_golden_cross')},
        'rsi14': snap.get('rsi14'),
        'kdj': {'k': snap.get('kdj_k'), 'd': snap.get('kdj_d'), 'j': snap.get('kdj_j')},
        'boll_pos': snap.get('boll_pos'),
        'vol_ratio': snap.get('vol_ratio'),
        'weekly_trend': snap.get('weekly_trend'),
        'monthly_trend': snap.get('monthly_trend'),
        'chg_5d': snap.get('chg_pct_5d'), 'chg_20d': snap.get('chg_pct_20d'),
    }
    name = q.name or symbol
    return {
        'ok': True,
        'symbol': symbol, 'name': name, 'market': market,
        'quote': {
            'price': q.price, 'change_pct': q.change_pct, 'change': q.change,
            'open': q.open, 'high': q.high, 'low': q.low, 'prev_close': q.prev_close,
            'volume': q.volume, 'amount': q.amount, 'turnover': q.turnover,
            'pe': q.pe, 'pb': q.pb, 'total_market_cap': q.total_market_cap,
            'timestamp': q.timestamp,
        },
        'kline': [{'date': b.date, 'open': b.open, 'close': b.close, 'low': b.low, 'high': b.high,
                   'volume': b.volume} for b in bars[-90:]],
        'tech': tech,
        'position': _position_label(closes, snap.get('rsi14')),
        'news': _related_news(symbol, name),
        'research': _research_items(symbol, name),
        'disclaimer': DISCLAIMER,
    }


def ai_comment(data: dict) -> dict:
    """AI 综合点评（无 Key/失败降级说明）"""
    try:
        from ..services.llm_client import chat
        from ..services.settings_service import ai_key_configured
        if not ai_key_configured():
            return {'ok': False, 'degraded': True, 'comment': '未配置 AI Key：以上为规则与技术面分析。配置 Key 后可获得 AI 综合点评。'}
        q = data['quote']
        t = data['tech']
        news = '；'.join((n.get('title') or '')[:60] for n in data['news'][:3]) or '无'
        research = '；'.join((r.get('title') or '')[:60] for r in data['research'][:3]) or '无'
        prompt = (
            f'你是 A股/港股个股分析助手。请基于以下数据对 {data["name"]}（{data["symbol"]}，{data["market"]}）做一次综合诊股，'
            '用 Markdown 输出：**一、概览与位置**（当前价/涨跌/60日区间位置【' + data['position'] + '】）'
            '；**二、技术面**（均线/趋势/MACD/RSI/量能，客观描述）；**三、估值与资金**（PE/PB/市值/量比/换手，说明数据缺失项）；'
            '**四、消息面**（列出相关资讯/研报要点）；**五、综合观点**（当前位置是否值得关注、可能的风险点、适合什么风格；'
            '保持谨慎措辞，不做买卖指令）。全文 600 字内，不得编造未提供的数据。\n\n'
            f'数据：现价 {q["price"]}，涨跌 {q["change_pct"]}%，成交额 {q["amount"]}，换手 {q["turnover"]}%，'
            f'PE {q["pe"]}，PB {q["pb"]}，市值 {q["total_market_cap"]}；'
            f'技术：{json.dumps(t, ensure_ascii=False)}；相关资讯：{news}；相关研报：{research}'
        )
        text = chat([{'role': 'user', 'content': prompt}], temperature=0.4, max_tokens=1200)
        text = (text or '').strip()
        return {'ok': bool(text), 'degraded': not bool(text),
                'comment': text or 'AI 点评生成失败，请稍后重试。'}
    except Exception as e:  # noqa: BLE001
        logger.warning('诊股 AI 点评失败: %s', str(e)[:120])
        return {'ok': False, 'degraded': True, 'comment': f'AI 点评暂时不可用：{str(e)[:120]}'}
