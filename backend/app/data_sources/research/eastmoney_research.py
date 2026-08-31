# -*- coding: utf-8 -*-
"""S13 研报数据源：东方财富研报中心（免费公开接口）+ 降级方案

实测（2026-08-31）：
- 可用接口：GET https://reportapi.eastmoney.com/report/list
  参数 industryCode=*&pageSize=N&industry=*&rating=*&ratingChange=*&beginTime=YYYY-MM-DD&endTime=YYYY-MM-DD&pageNo=1&qType=0&code=*
  返回 UTF-8 JSON：data[] 含 title / stockName / stockCode / orgSName / publishDate /
  emRatingName（买入/增持…）/ ratingChange / indvAimPriceT|indvAimPriceL（目标价）/ infoCode。
  研报 PDF 全文：https://pdf.dfcfw.com/pdf/H3_{infoCode}_1.pdf（实测 200 application/pdf）。
- 不可用接口：带 cb=datatable 的变体缺少 beginTime 参数返回 400，不采用。

降级方案：东财接口不可用/为空时，改用本地 news_cache 中标题含「研报|评级|目标价」的资讯
作为替代数据源（source='news_cache'，字段来源在注释与本模块 docstring 中说明）。
"""

import json
import re
import time
from datetime import datetime, timedelta

import requests

from ...models.database import get_connection
from ...services.logger import get_agent_logger

logger = get_agent_logger()

RESEARCH_URL = 'https://reportapi.eastmoney.com/report/list'
PDF_URL = 'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
FALLBACK_TITLE_KW = ('研报', '评级', '目标价')
_LAST_FETCH: dict[str, tuple[float, list[dict]]] = {}  # 轻量内存缓存（keyword -> (ts, items)）
CACHE_TTL = 600.0


def _month_range() -> tuple[str, str]:
    """当月起止日期（研报接口的 beginTime/endTime）"""
    now = datetime.now()
    first = now.replace(day=1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return first.strftime('%Y-%m-%d'), last.strftime('%Y-%m-%d')


def _normalize(items: list[dict], source: str) -> list[dict]:
    """统一研报条目结构：{title, org, rating, rating_change, target_price, date, stock, url, source}"""
    out: list[dict] = []
    for it in items:
        title = (it.get('title') or '').strip()
        if not title:
            continue
        tp = it.get('indvAimPriceT') or it.get('indvAimPriceL')
        try:
            target = round(float(tp), 2) if tp not in (None, '') else None
        except (TypeError, ValueError):
            target = None
        out.append({
            'title': title,
            'org': it.get('orgSName') or it.get('orgName') or '',
            'rating': it.get('emRatingName') or '',
            'rating_change': it.get('ratingChange') or '',
            'target_price': target,
            'date': (it.get('publishDate') or '')[:10],
            'stock': {'name': it.get('stockName') or '', 'code': it.get('stockCode') or ''},
            'url': PDF_URL.format(info=it.get('infoCode')) if it.get('infoCode') else '',
            'source': source,
        })
    return out


def _fetch_eastmoney(limit: int = 30) -> list[dict]:
    """东财研报接口拉取（返回原始条目列表；失败抛异常由调用方降级）"""
    begin, end = _month_range()
    params = {
        'industryCode': '*', 'pageSize': max(limit, 10), 'industry': '*',
        'rating': '*', 'ratingChange': '*', 'beginTime': begin, 'endTime': end,
        'pageNo': 1, 'qType': 0, 'code': '*',
    }
    r = requests.get(RESEARCH_URL, params=params, headers={'User-Agent': UA}, timeout=15)
    r.raise_for_status()
    data = json.loads(r.content.decode('utf-8', errors='replace'))
    items = data.get('data') or []
    return items[:limit]


def _fallback_from_news(keyword: str | None, limit: int) -> list[dict]:
    """降级源：news_cache 中标题/摘要含 研报|评级|目标价 的资讯（keyword 可选过滤）"""
    conn = get_connection()
    try:
        if keyword:
            rows = conn.execute(
                "SELECT title, url, source, summary, published_at FROM news_cache "
                "WHERE (title LIKE ? OR summary LIKE ?) "
                "AND (title LIKE '%研报%' OR title LIKE '%评级%' OR title LIKE '%目标价%') "
                "ORDER BY id DESC LIMIT ?",
                (f'%{keyword}%', f'%{keyword}%', limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT title, url, source, summary, published_at FROM news_cache "
                "WHERE title LIKE '%研报%' OR title LIKE '%评级%' OR title LIKE '%目标价%' "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    items: list[dict] = []
    for r in rows:
        items.append({
            'title': r['title'],
            'org': r['source'] or '',
            'rating': '',
            'rating_change': '',
            'target_price': None,
            'date': (r['published_at'] or '')[:10],
            'stock': {'name': '', 'code': ''},
            'url': r['url'] or '',
            'source': 'news_cache',
        })
    return items


def fetch_research(keyword: str | None = None, limit: int = 10) -> dict:
    """研报列表：优先东财接口；失败/为空降级 news_cache。
    返回 {ok, source: 'eastmoney'|'news_cache', items: [...], note?}"""
    limit = max(1, min(int(limit), 50))
    keyword = (keyword or '').strip() or None
    cache_key = keyword or '*'
    cached = _LAST_FETCH.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL:
        return {'ok': True, 'source': 'eastmoney', 'items': cached[1][:limit], 'note': '缓存数据'}

    try:
        raw = _fetch_eastmoney(max(limit * 3, 30))
        items = _normalize(raw, 'eastmoney')
        if keyword:
            kw = keyword.lower()
            items = [it for it in items
                     if kw in it['title'].lower()
                     or kw in it['stock']['name'].lower()
                     or kw == it['stock']['code'].lower()]
        items = items[:limit]
        if items:
            _LAST_FETCH[cache_key] = (time.time(), items)
            return {'ok': True, 'source': 'eastmoney', 'items': items}
        raise RuntimeError('东财研报返回为空')
    except Exception as e:  # noqa: BLE001
        logger.warning('东财研报不可用，降级 news_cache: %s', str(e)[:120])
        items = _fallback_from_news(keyword, limit)
        note = '东财研报接口不可用，已降级使用本地资讯缓存（标题含 研报/评级/目标价）'
        return {'ok': bool(items), 'source': 'news_cache', 'items': items, 'note': note}


def _holding_related(item: dict) -> tuple[bool, str]:
    """研报股票是否在用户持仓中（代码或名称匹配）"""
    conn = get_connection()
    try:
        rows = conn.execute('SELECT symbol, name FROM holdings').fetchall()
    finally:
        conn.close()
    stock = item.get('stock') or {}
    code, name = stock.get('code') or '', stock.get('name') or ''
    for r in rows:
        if (code and r['symbol'] == code) or (name and r['name'] and name in r['name']):
            return True, f"{r['name']}（{r['symbol']}）"
    return False, ''


def _template_interpret(item: dict) -> str:
    """研报解读降级模板：列出研报标题/机构/评级原文"""
    stock = item.get('stock') or {}
    stock_txt = f"{stock.get('name')}（{stock.get('code')}）" if stock.get('code') else (stock.get('name') or '')
    lines = [
        '【研报解读｜未配置有效 AI Key 或 AI 服务暂不可用，以下为研报原文信息】',
        f"标题：{item.get('title')}",
    ]
    if stock_txt:
        lines.append(f"标的：{stock_txt}")
    if item.get('org'):
        lines.append(f"机构：{item.get('org')}")
    if item.get('rating'):
        lines.append(f"评级：{item.get('rating')}")
    if item.get('target_price') is not None:
        lines.append(f"目标价：{item.get('target_price')}")
    if item.get('date'):
        lines.append(f"发布日期：{item.get('date')}")
    lines.append('配置有效 DeepSeek API Key 后，可自动提取目标价/评级变化/关键假设/风险提示并生成 300 字以内摘要。')
    lines.append('以上内容仅供参考，不构成投资建议。')
    return '\n'.join(lines)


def interpret_research(keyword: str | None = None, title: str | None = None) -> dict:
    """研报 AI 解读：定位研报 → AI 提取核心观点（目标价/评级变化/关键假设/风险提示，300 字摘要）
    + 持仓关联分析；无 Key 或失败走降级模板。
    返回 {ok, research, interpretation, holding_related, holding_match?, degraded, source}"""
    if not (keyword or '').strip() and not (title or '').strip():
        return {'ok': False, 'error': '需要 keyword 或 title 参数'}
    query = (title or '').strip() or (keyword or '').strip()
    result = fetch_research(keyword=query, limit=5)
    if not result.get('ok') or not result.get('items'):
        return {'ok': False, 'error': '未找到相关研报（数据源不可用且无降级资讯）',
                'source': result.get('source')}
    # 标题精确匹配优先
    item = None
    for it in result['items']:
        if title and it['title'] == title.strip():
            item = it
            break
    if item is None:
        item = result['items'][0]
    related, match = _holding_related(item)

    try:
        from ...services.llm_client import chat
        from ...services.settings_service import ai_key_configured
        from ...utils.prompts.research_prompt import build_interpret_prompt
        if ai_key_configured():
            prompt = build_interpret_prompt(item)
            text = chat([{'role': 'user', 'content': prompt}], temperature=0.3, max_tokens=800)
            text = (text or '').strip()
            if text:
                return {'ok': True, 'research': item, 'interpretation': text,
                        'holding_related': related, 'holding_match': match,
                        'degraded': False, 'source': result.get('source')}
    except Exception as e:  # noqa: BLE001
        logger.warning('研报 AI 解读失败，降级模板: %s', str(e)[:120])

    return {'ok': True, 'research': item, 'interpretation': _template_interpret(item),
            'holding_related': related, 'holding_match': match,
            'degraded': True, 'source': result.get('source')}
