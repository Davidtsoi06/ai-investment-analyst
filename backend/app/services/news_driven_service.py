# -*- coding: utf-8 -*-
"""V1.2.0 消息面 / 政策面驱动推荐引擎

流程：本地资讯（近 30 天）→ 主题聚类 + AI 推断受益标的（含未点名产业链个股）
      → 行情/技术校验（位置、20 日涨幅，防追高）→ 生成推荐条目（带 driver 与信源）

无 AI Key 时降级：仅识别资讯标题中直接出现的公司名（不做产业链推断），并在 notes 中注明。
"""

import json
import re
import time

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection
from .logger import get_app_logger

logger = get_app_logger()

# 政策类资讯识别关键词（政策面引擎）
POLICY_KEYWORDS = (
    '国务院', '发改委', '工信部', '能源局', '证监会', '央行', '财政部', '科技部', '住建部',
    '规划', '试点', '补贴', '标准', '指导意见', '行动方案', '白皮书', '政策', '部委', '国常会',
    '中央', '通知', '办法', '条例', '十四五', '十五五', '专项债', '税收优惠', '产业基金',
)

_NEWS_LIMIT = 60
_DAYS_WINDOW = 30


def _collect_news(kind: str, focus: str = '') -> list[dict]:
    """取本地资讯（近 30 天，最多 60 条）；kind='policy' 时仅保留政策类资讯"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT title, summary, source, url, published_at, region FROM news_cache "
            "ORDER BY id DESC LIMIT ?",
            (_NEWS_LIMIT * 2,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for r in rows:
        title = (r['title'] or '').strip()
        if not title:
            continue
        summary = (r['summary'] or '').strip()
        text = title + ' ' + summary
        if kind == 'policy' and not any(k in text for k in POLICY_KEYWORDS):
            continue
        if focus:
            # 关注领域过滤（用户输入，如「新能源、半导体」）：命中任一关键词才纳入
            kws = [w.strip() for w in re.split(r'[,，、\s]+', focus) if w.strip()]
            if kws and not any(k in text for k in kws):
                continue
        out.append({
            'title': title,
            'summary': summary[:160],
            'source': r['source'] or '',
            'url': r['url'] or '',
            'date': (r['published_at'] or '')[:10],
            'region': r['region'] or '',
        })
        if len(out) >= _NEWS_LIMIT:
            break
    return out


def _ai_themes(news_items: list[dict], kind: str, focus: str = '') -> tuple[list[dict], str]:
    """一次 AI 调用：主题聚类 + 受益标的推断。返回 (themes, error)"""
    from .llm_client import chat
    from ..config import settings
    from .settings_service import ai_key_configured
    if not ai_key_configured():
        return [], '未配置 AI Key'
    if not news_items:
        return [], '资讯库近期无可用条目（可先到资讯看板抓取）'
    lines = []
    for n in news_items[:40]:
        lines.append(f"- [{n['date']}] {n['title']}（{n['source']}）{n['summary'][:80]}")
    kind_txt = '政策文件与政策动向' if kind == 'policy' else '财经/产业新闻'
    focus_txt = f'\n用户特别关注领域：{focus}（优先分析该领域，其它领域仅在明显重要时纳入）' if focus else ''
    prompt = (
        f'你是资深 A 股/港股投资研究员。以下是我抓取到的近期{kind_txt}（含来源与日期）。\n'
        '请完成：① 把资讯归纳为若干「投资主题」；② 对每个主题推断**受益标的**（A股 6 位代码 / 港股 5 位代码）。\n'
        '重要：不仅列出被资讯直接点名的公司，也要基于产业链知识给出**尚未被点名的受益个股**'
        '（例如「钻石散热」→ 黄河旋风、力量钻石、四方达等），并在 reason 中说明受益逻辑。\n'
        f'{focus_txt}\n'
        '只输出 JSON 数组，每项格式：\n'
        '{"theme":"主题名","trigger":{"title":"最相关的资讯标题","date":"YYYY-MM-DD","source":"来源"},\n'
        ' "reason":"为什么这些标的受益（一两句）","stage":"early|fermenting|hot",\n'
        ' "horizon":"短线|长线","confidence":40-95,\n'
        ' "symbols":[{"symbol":"600172","name":"黄河旋风","market":"A股","reason":"受益逻辑一句"}]}\n'
        'stage 含义：early=消息刚出现、标的尚未大涨；fermenting=正在发酵；hot=已被市场充分消化。\n'
        '每个主题给 1~6 只标的，最多 5 个主题。资讯列表：\n' + '\n'.join(lines)
    )
    try:
        text = chat([{'role': 'user', 'content': prompt}],
                    model=settings.model_chat, temperature=0.3, max_tokens=4000)
        fence = chr(96) * 3
        text = re.sub(rf'^\s*{fence}json\s*', '', text.strip())
        text = re.sub(rf'{fence}\s*$', '', text)
        if not text.strip().startswith('['):
            idx = text.find('[')
            if idx >= 0:
                text = text[idx:]
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        return [], f'AI 分析失败：{str(e)[:120]}'
    if not isinstance(data, list):
        return [], 'AI 返回格式无法解析'
    out: list[dict] = []
    for t in data:
        if not isinstance(t, dict) or not t.get('theme'):
            continue
        syms = [s for s in (t.get('symbols') or []) if isinstance(s, dict) and s.get('symbol')]
        if not syms:
            continue
        out.append({
            'theme': str(t.get('theme'))[:40],
            'trigger': t.get('trigger') if isinstance(t.get('trigger'), dict) else {},
            'reason': str(t.get('reason') or '')[:160],
            'stage': t.get('stage') if t.get('stage') in ('early', 'fermenting', 'hot') else 'fermenting',
            'horizon': '长线' if t.get('horizon') == '长线' else '短线',
            'confidence': max(40, min(95, int(t.get('confidence') or 60))) if str(t.get('confidence') or '60').isdigit() else 60,
            'symbols': syms[:6],
        })
    return out[:5], ''


_STAGE_CN = {'early': '早期埋伏', 'fermenting': '发酵中', 'hot': '已高潮'}


def _verify_and_build(theme: dict, kind: str) -> list[dict]:
    """技术校验（位置/20 日涨幅，防追高）+ 构造推荐条目"""
    entries: list[dict] = []
    for s in theme['symbols']:
        symbol = str(s.get('symbol') or '').strip()
        market = '港股' if (len(symbol) == 5 and symbol.startswith('0')) else 'A股'
        try:
            q = data_fusion.get_quote(symbol, market)
            if q is None:
                continue
            bars = data_fusion.get_kline(symbol, market, 60)
        except Exception:  # noqa: BLE001
            continue
        stage = theme['stage']
        if bars and len(bars) > 21:
            close = float(bars[-1].close)
            chg20 = (close / float(bars[-21].close) - 1) * 100 if float(bars[-21].close) else 0.0
            lows = [float(b.close) for b in bars[-60:]]
            hi, lo = max(lows), min(lows)
            pos = (close - lo) / (hi - lo) if hi > lo else 0.5
            if chg20 > 30 or pos > 0.85:
                stage = 'hot'  # 已被消化/追高区
        price = float(q.price or 0)
        if price <= 0:
            continue
        conf = theme['confidence']
        if stage == 'hot':
            conf = max(40, conf - 15)
        # 条目字段（短线给出入场/止损/目标；长线给出估值区间）
        entry_min = round(price * 0.99, 2)
        entry_max = round(price * 1.02, 2)
        row = {
            'symbol': symbol, 'name': str(s.get('name') or (q.name or symbol))[:20],
            'market': market, 'rec_type': theme['horizon'],
            'entry_min': entry_min, 'entry_max': entry_max,
            'stop_loss': round(price * 0.95, 2),
            'target': round(price * (1.08 if theme['horizon'] == '短线' else 1.15), 2),
            'valuation_min': round(price * 0.92, 2), 'valuation_max': round(price * 1.08, 2),
            'confidence': conf,
            'logic': '',  # 由 _compose_logic 填充
            # V1.2.0：风险细分——早期/发酵中按"中"（允许稳健型画像纳入），已高潮按"高"
            'risk_level': '高' if stage == 'hot' else '中',
            'price': price,
            'tier': 'rec' if conf >= 60 else 'watch',
            'driver': kind,
            'sources': [],
        }
        row['logic'] = _compose_logic(theme, s, kind, stage)
        entries.append(row)
    return entries


def _compose_logic(theme: dict, sym: dict, kind: str, stage: str) -> str:
    tag = '🏛️ 政策面' if kind == 'policy' else '📰 消息面'
    trigger = theme.get('trigger') or {}
    trig_txt = f"{trigger.get('title') or theme['theme']}（{trigger.get('source') or '资讯'} · {trigger.get('date') or ''}）"
    why = str(sym.get('reason') or theme.get('reason') or '')[:90]
    return f"{tag}：{trig_txt}｜受益逻辑：{why}｜阶段：{_STAGE_CN.get(stage, stage)}"


def _sources_of(theme: dict, news_items: list[dict]) -> list[dict]:
    """信源：优先 trigger 对应资讯，其次标题最相关的 1~2 条（最多 3 条）"""
    out: list[dict] = []
    trig = theme.get('trigger') or {}
    t_title = str(trig.get('title') or '')
    for n in news_items:
        if not n.get('url'):
            continue
        if t_title and (n['title'][:12] in t_title or t_title[:12] in n['title']):
            out.append({'title': n['title'], 'url': n['url'], 'source': n['source'], 'date': n['date']})
            break
    for n in news_items:
        if len(out) >= 3:
            break
        if not n.get('url') or any(o['url'] == n['url'] for o in out):
            continue
        if theme['theme'][:2] in (n['title'] + n['summary']):
            out.append({'title': n['title'], 'url': n['url'], 'source': n['source'], 'date': n['date']})
    if not out and news_items:
        n = news_items[0]
        if n.get('url'):
            out.append({'title': n['title'], 'url': n['url'], 'source': n['source'], 'date': n['date']})
    return out[:3]


def _fallback_entries(news_items: list[dict], kind: str, quota: int) -> tuple[list[dict], str]:
    """无 AI 降级：仅识别资讯标题中直接出现的公司名（本地词典 + 多源搜索）"""
    from ..data_sources.market.stock_search import search_stocks
    entries: list[dict] = []
    seen: set = set()
    for n in news_items:
        if len(entries) >= quota:
            break
        title = n['title']
        for kw in re.findall(r'[\u4e00-\u9fa5A-Za-z]{2,8}', title):
            if kw in seen or len(kw) < 2:
                continue
            seen.add(kw)
            try:
                cands = search_stocks(kw, 1)
            except Exception:  # noqa: BLE001
                cands = []
            if not cands:
                continue
            c = cands[0]
            if c['name'][:2] not in title and kw not in title:
                continue
            try:
                q = data_fusion.get_quote(c['symbol'], c['market'])
            except Exception:  # noqa: BLE001
                q = None
            if q is None or not q.price:
                continue
            price = float(q.price)
            tag = '🏛️ 政策面' if kind == 'policy' else '📰 消息面'
            entries.append({
                'symbol': c['symbol'], 'name': c['name'], 'market': c['market'], 'rec_type': '短线',
                'entry_min': round(price * 0.99, 2), 'entry_max': round(price * 1.02, 2),
                'stop_loss': round(price * 0.95, 2), 'target': round(price * 1.08, 2),
                'valuation_min': round(price * 0.92, 2), 'valuation_max': round(price * 1.08, 2),
                'confidence': 55, 'risk_level': '中', 'price': price, 'tier': 'watch',
                'driver': kind,
                'sources': [{'title': n['title'], 'url': n['url'], 'source': n['source'], 'date': n['date']}],
                'logic': f"{tag}：{n['title']}（{n['source']} · {n['date']}）｜降级模式：仅识别被资讯点名的公司（配置 AI Key 后可推断产业链受益股）",
            })
            break
    return entries, 'fallback'


def build_driver_entries(kind: str, quota: int = 3, focus: str = '') -> dict:
    """入口：kind='news'|'policy'；返回 {entries, notes, error}
    - entries：推荐条目（含 driver / sources）
    - notes：提示信息（降级说明、信源不足等）
    """
    news_items = _collect_news(kind, focus)
    if not news_items:
        msg = '资讯库近 30 天无政策类条目（可先抓取资讯）' if kind == 'policy' else '资讯库近 30 天无条目（可先到资讯看板抓取）'
        return {'entries': [], 'notes': [msg], 'error': msg}
    themes, err = _ai_themes(news_items, kind, focus)
    if not themes:
        # 降级：仅识别被点名公司
        entries, _ = _fallback_entries(news_items, kind, quota)
        note = f'AI 不可用（{err}），已降级为「仅识别被资讯点名的公司」'
        return {'entries': entries[:quota], 'notes': [note], 'error': None}
    entries: list[dict] = []
    for t in themes:
        srcs = _sources_of(t, news_items)
        built = _verify_and_build(t, kind)
        for e in built:
            e['sources'] = srcs
            entries.append(e)
    # 去重（同 symbol+rec_type 保留置信度最高）
    best: dict = {}
    for e in entries:
        k = (e['symbol'], e['rec_type'])
        if k not in best or e['confidence'] > best[k]['confidence']:
            best[k] = e
    ordered = sorted(best.values(), key=lambda x: -x['confidence'])[:max(1, quota)]
    notes = [f'共识别 {len(themes)} 个主题（{kind == "policy" and "政策面" or "消息面"}），命中 {len(ordered)} 只标的']
    return {'entries': ordered, 'notes': notes, 'error': None}
