# -*- coding: utf-8 -*-
"""V1.1.0 M1：我的股票池体检（高低位判定，规则实现；AI 点评可选）"""

import json

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection
from ..services.indicators import sma
from .logger import get_app_logger

logger = get_app_logger()


def _position_of(closes: list[float], snap: dict) -> dict:
    """位置判定（图例口径，V1.1.0）：
    - 近 60 日价格区间分位：>0.75 高位 / <0.25 低位 / 其余中位
    - RSI>70 高位警示；RSI<30 低位警示；MA20 乖离率辅助
    返回 {position, position_label, pct, rsi, ma_bias}"""
    position = 'mid'
    pct = 0.5
    rsi = snap.get('rsi14')
    low = min(closes[-60:])
    high = max(closes[-60:])
    if high > low:
        pct = round((closes[-1] - low) / (high - low), 3)
    if pct > 0.75:
        position = 'high'
    elif pct < 0.25:
        position = 'low'
    if rsi is not None:
        if float(rsi) > 70 and position != 'high':
            position = 'high'
        elif float(rsi) < 30 and position != 'low':
            position = 'low'
    ma_bias = None
    ma20 = sma(closes, 20)
    if ma20 and ma20[-1]:
        ma_bias = round((closes[-1] / float(ma20[-1]) - 1) * 100, 2)
    label = {'high': '高位', 'mid': '中位', 'low': '低位'}[position]
    return {'position': position, 'position_label': label, 'pct': pct, 'rsi': rsi, 'ma_bias': ma_bias}


def _rule_verdict(position: str, snap: dict, pe) -> dict:
    """规则结论：值得关注 / 观望 / 回避（一句话理由）"""
    ma = snap.get('ma_status') or ''
    trend = str(snap.get('weekly_trend') or '')
    if position == 'low' and ('多头' in trend or ma == '多头排列'):
        return {'verdict': '值得关注', 'reason': '处于低位区间且周线/均线转多，可研究分批布局机会'}
    if position == 'low':
        return {'verdict': '观望', 'reason': '处于低位区间但趋势尚未转多，等待企稳信号再评估'}
    if position == 'high' and float(rsi if (rsi := snap.get('rsi14')) is not None else 50) > 70:
        return {'verdict': '回避追高', 'reason': '高位且 RSI 超买，追高风险大，宜等回调'}
    if position == 'high':
        return {'verdict': '观望', 'reason': '处于 60 日高位区间，性价比一般，持盈者可考虑分批止盈'}
    return {'verdict': '值得关注', 'reason': '处于中位区间，结合量与趋势择机参与'}


def analyze_pool(groups: list[str] | None = None) -> dict:
    """分析我的股票池：{items:[{symbol,name,market,group,price,change_pct,position...,verdict,reason}], errors}"""
    conn = get_connection()
    try:
        if groups:
            marks = ','.join('?' * len(groups))
            rows = conn.execute(
                f'SELECT symbol, name, market, group_name FROM watchlist WHERE group_name IN ({marks}) '
                'ORDER BY group_name, CAST(symbol AS INTEGER), id',
                groups,
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT symbol, name, market, group_name FROM watchlist ORDER BY group_name, CAST(symbol AS INTEGER), id'
            ).fetchall()
    finally:
        conn.close()

    items: list[dict] = []
    errors: list[str] = []
    # 组市场范围：限定市场的表只分析该市场股票（v1.1.3）
    c2 = get_connection()
    try:
        gm = {r['name']: r['market'] for r in c2.execute('SELECT name, market FROM watch_groups')}
    finally:
        c2.close()
    for r in rows:
        d = dict(r)
        gmarket = gm.get(d['group_name'] or '', '')
        if gmarket and d['market'] != gmarket:
            errors.append(f"{d['name'] or d['symbol']}：表「{d['group_name']}」限 {gmarket}，已跳过（可在管理表中调整范围）")
            continue
        try:
            q = data_fusion.get_quote(d['symbol'], d['market'])
            if q is None:
                errors.append(f"{d['symbol']}：行情获取失败")
                continue
            bars = data_fusion.get_kline(d['symbol'], d['market'], 60)
            if not bars:
                errors.append(f"{d['symbol']}：K线获取失败")
                continue
            closes = [float(b.close) for b in bars]
            from ..services.indicators import indicator_snapshot
            snap = indicator_snapshot(bars) or {}
            pos = _position_of(closes, snap)
            verdict = _rule_verdict(pos['position'], snap, q.pe)
            # V1.1.6：最新资讯 + 消息情绪 + 四档操作建议
            news = _related_news(d['name'] or q.name or d['symbol'], d['symbol'], 3)
            sentiment = _sentiment_of(news)
            act = _action_of(pos['position'], snap, sentiment, bool(news))
            items.append({
                'symbol': d['symbol'], 'name': d['name'] or q.name or d['symbol'],
                'market': d['market'], 'group': d['group_name'] or '默认',
                'price': q.price, 'change_pct': q.change_pct,
                **pos, **verdict,
                'pe': q.pe,
                'news': news, 'sentiment': sentiment, **act,
            })
        except Exception as e:  # noqa: BLE001
            logger.warning('股票池分析 %s 失败: %s', d['symbol'], str(e)[:100])
            errors.append(f"{d['symbol']}：{str(e)[:60]}")
    return {'items': items, 'errors': errors, 'count': len(items)}


# ---------------- V1.1.6 体检增强：最新资讯 / 情绪 / 四档建议 / AI 深度点评 ----------------

_SENTI_BULL = ('中标', '签约', '订单', '回购', '增持', '预增', '增长', '大涨', '突破', '获批',
               '重组', '并表', '分红', '提价', '涨价', '专利', '量产', '放量', '新高', '扭亏',
               '利好', '合作', '扩产', '出口', '高增', '超预期')
_SENTI_BEAR = ('减持', '亏损', '预减', '下滑', '大跌', '处罚', '立案', '违规', '诉讼', '解禁',
               '降价', '召回', '退市', '风险警示', '暴雷', '下调', '裁员', '利空', '警示', '问询', '调查')


def _related_news(name: str, symbol: str, limit: int = 3) -> list[dict]:
    """本地资讯库按名称/代码命中的最新资讯（含海外标题中文）；无本地资讯返回 []"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT title, source, url, published_at FROM news_cache "
            "WHERE (title LIKE ? OR summary LIKE ?) OR (title LIKE ? OR summary LIKE ?) "
            "ORDER BY id DESC LIMIT ?",
            (f'%{name}%', f'%{name}%', f'%{symbol}%', f'%{symbol}%', limit),
        ).fetchall()
        out = []
        for row in rows:
            out.append({'title': row['title'], 'source': row['source'], 'url': row['url'],
                        'published': (row['published_at'] or '')[:10]})
        return out
    finally:
        conn.close()


def _sentiment_of(news: list[dict]) -> str:
    """消息情绪：利多 / 利空 / 中性（标题关键词计数）"""
    bull = bear = 0
    for n in news:
        t = str(n.get('title') or '')
        bull += sum(1 for w in _SENTI_BULL if w in t)
        bear += sum(1 for w in _SENTI_BEAR if w in t)
    if bull > bear:
        return '利多'
    if bear > bull:
        return '利空'
    return '中性'


def _action_of(position: str, snap: dict, sentiment: str, has_news: bool) -> dict:
    """四档操作建议：买入/持有/减仓/观望（技术位置 × 消息情绪 × 趋势）"""
    rsi = snap.get('rsi14')
    rsi_high = rsi is not None and float(rsi) > 70
    trend = str(snap.get('weekly_trend') or '') + str(snap.get('ma_status') or '')
    multi = '多头' in trend
    if has_news:
        s_txt = '利多' if sentiment == '利多' else ('利空' if sentiment == '利空' else '中性')
        news_note = f'；消息面{s_txt}（最新资讯匹配）'
    else:
        news_note = '；暂无本地相关资讯（消息面按中性计）'
    if position == 'low':
        if sentiment == '利多':
            return {'action': '买入', 'action_reason': '低位区间且消息面偏多，可分批建仓' + news_note}
        return {'action': '观望', 'action_reason': '低位区间但消息面未转多，等待企稳信号' + news_note}
    if position == 'high':
        if rsi_high:
            return {'action': '减仓', 'action_reason': '高位且 RSI 超买，宜分批减仓落袋' + news_note}
        if sentiment == '利多' and multi:
            return {'action': '持有', 'action_reason': '高位但趋势与消息面仍偏多，持有并设好止盈位' + news_note}
        if sentiment == '利空':
            return {'action': '减仓', 'action_reason': '高位叠加消息面偏空，建议减仓避险' + news_note}
        return {'action': '减仓', 'action_reason': '60 日高位区间、性价比下降，可分批止盈' + news_note}
    # 中位
    if sentiment == '利多' and multi:
        return {'action': '买入', 'action_reason': '中位区间、趋势偏多且消息面利多，可分批介入' + news_note}
    if sentiment == '利多':
        return {'action': '观望', 'action_reason': '消息面偏多但趋势未确认，等回踩企稳再介入' + news_note}
    if sentiment == '利空':
        return {'action': '减仓', 'action_reason': '中位但消息面偏空，注意控制仓位' + news_note}
    if multi:
        return {'action': '持有', 'action_reason': '中位区间、趋势偏多，可继续持有观察' + news_note}
    return {'action': '观望', 'action_reason': '中位区间、方向未明，观望为主' + news_note}


def ai_pool_comment(groups: list[str] | None = None) -> dict:
    """V1.1.6 AI 深度点评：一次调用对全池输出 买入/持有/减仓/观望 + 理由（结合最新资讯）；
    无 Key/失败返回 {ok:False, reason}（前端回落规则建议）"""
    from ..services.llm_client import chat
    from ..config import settings
    from ..services.settings_service import ai_key_configured
    if not ai_key_configured():
        return {'ok': False, 'reason': '未配置 DeepSeek API Key（配置后可用 AI 深度点评）'}
    base = analyze_pool(groups) or {}
    items = base.get('items') or []
    if not items:
        return {'ok': False, 'reason': '池内暂无股票可分析（' + (base.get('errors') or ['无'])[0] + '）'}
    lines = []
    for it in items:
        news = '；'.join(n['title'] for n in (it.get('news') or [])[:2]) or '（无本地资讯）'
        lines.append(
            f"{it['symbol']} {it['name']}（{it['market']}）：现价 {it.get('price')}，"
            f"60日{it.get('position_label')}，RSI {it.get('rsi')}，规则结论：{it.get('action')}（{it.get('action_reason')}），"
            f"相关资讯：{news}")
    prompt = (
        '你是资深 A 股/港股投资顾问。以下是我的自选股票池体检结果（含最新相关资讯），请对每只给出明确操作建议。\n'
        '要求：只输出 JSON 数组，每项 {"symbol":"代码", "action":"买入|持有|减仓|观望", "reason":"一句话理由(40字内,引用具体资讯或指标)"}；\n'
        '数量必须等于输入股票数，逐一对应，不要遗漏。输入：\n' + '\n'.join(lines))
    try:
        text = chat([{'role': 'user', 'content': prompt}],
                    model=settings.model_chat, temperature=0.2, max_tokens=4000)
        import re as _re
        fence = chr(96) * 3
        text = _re.sub(rf'^\s*{fence}json\s*', '', text.strip())
        text = _re.sub(rf'{fence}\s*$', '', text)
        data = json.loads(text) if text.strip().startswith('[') else None
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'reason': f'AI 点评失败：{str(e)[:120]}（请稍后重试，或使用规则建议）'}
    if not isinstance(data, list) or not data:
        return {'ok': False, 'reason': 'AI 返回内容无法解析，请稍后重试或使用规则建议'}
    by_sym = {str(x.get('symbol')): x for x in data if x.get('symbol')}
    out = []
    for it in items:
        x = by_sym.get(str(it['symbol'])) or {}
        act = x.get('action') if x.get('action') in ('买入', '持有', '减仓', '观望') else it.get('action')
        out.append({'symbol': it['symbol'], 'action': act,
                   'reason': str(x.get('reason') or it.get('action_reason') or '')[:160], 'ai': True})
    return {'ok': True, 'items': out}
