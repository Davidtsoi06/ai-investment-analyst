# -*- coding: utf-8 -*-
"""资讯聚合 Agent：抓取 → 去重 → AI 分级摘要（无 Key 降级规则）→ 持仓关联 → 盘前内容生成"""

import hashlib
import json
import re

from ..data_sources.news import fetch_news, NewsItem
from ..data_sources.news.news_dedup import dedup_in_batch, is_duplicate
from ..models.database import get_connection, utc_now
from ..utils.prompts.news_prompt import build_classify_prompt
from ..services.logger import get_agent_logger

logger = get_agent_logger()

MAJOR_KEYWORDS = ['央行', '降息', '加息', '美联储', '国常会', '政治局', '证监会', '监管', '并购重组', '重大资产', '财报', '业绩', '解禁', 'IPO', '黑天鹅', '降准', 'LPR']
MID_KEYWORDS = ['行业', '板块', '指数', '资金', '北向', '南向', '高盛', '摩根', '评级', '半导体', '新能源', '科技', '地产', '银行', '券商']


def _rule_level(title: str) -> str:
    for kw in MAJOR_KEYWORDS:
        if kw in title:
            return '重大'
    for kw in MID_KEYWORDS:
        if kw in title:
            return '中等'
    return '一般'


def _get_holdings() -> list[str]:
    from ..services.portfolio_sync import get_mode
    src = 'portfolio_app' if get_mode() == 'snapshot' else 'manual'
    conn = get_connection()
    try:
        rows = conn.execute('SELECT name, symbol FROM holdings WHERE source = ?', (src,)).fetchall()
        return [r['name'] for r in rows] + [r['symbol'] for r in rows]
    finally:
        conn.close()


def _content_hash(title: str, url: str) -> str:
    return hashlib.md5((title + url).encode('utf-8')).hexdigest()


def _load_recent_titles(limit: int = 50) -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute('SELECT title FROM news_cache ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [r['title'] for r in rows]
    finally:
        conn.close()


def _ai_classify(items: list[NewsItem], holdings: list[str]) -> dict[str, dict] | None:
    """DeepSeek 分级摘要；失败或无 Key 返回 None（走规则降级）"""
    try:
        from ..services.llm_client import chat
        from ..services.settings_service import ai_key_configured
        if not ai_key_configured():
            return None
        prompt = build_classify_prompt(items[:20], holdings)
        text = chat([{'role': 'user', 'content': prompt}], temperature=0.2, max_tokens=1500)
        text = re.sub(r'^```json\s*|```\s*$', '', text.strip())
        data = json.loads(text)
        return {str(d.get('index')): d for d in data if isinstance(d, dict)}
    except Exception as e:  # noqa: BLE001
        logger.warning('AI 分级失败，降级规则: %s', str(e)[:100])
        return None


def collect_and_analyze() -> dict:
    """抓取 → 去重 → 分级 → 持仓关联 → 入库；返回汇总"""
    raw = fetch_news()
    if not raw:
        return {'ok': False, 'reason': '资讯抓取失败（数据源不可用）', 'items': []}
    items = dedup_in_batch(raw)
    recent = _load_recent_titles()
    items = [it for it in items if not is_duplicate(it.title, recent)]
    holdings = _get_holdings()

    ai_map = _ai_classify(items, holdings)
    conn = get_connection()
    saved = 0
    result_items: list[dict] = []
    try:
        for i, it in enumerate(items):
            if ai_map and str(i + 1) in ai_map:
                info = ai_map[str(i + 1)]
                level = info.get('level', '一般')
                summary = info.get('summary', it.summary or it.title)
            else:
                level = _rule_level(it.title)
                summary = it.summary or it.title
            holding_related = any(h and h in (it.title + it.summary) for h in holdings)
            cur = conn.execute(
                '''INSERT OR IGNORE INTO news_cache
                (title, url, source, market, summary, level, content_hash, published_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'''
                , (
                it.title, it.url, it.source, it.market, summary, level,
                _content_hash(it.title, it.url), it.published_at, utc_now(),
            ))
            if cur.rowcount > 0:
                saved += 1
            result_items.append({
                'title': it.title, 'url': it.url, 'source': it.source, 'market': it.market,
                'summary': summary, 'level': level, 'holding_related': holding_related,
                'published_at': it.published_at,
            })
        conn.commit()
    finally:
        conn.close()
    logger.info('资讯整合完成: 抓取 %d 条 → 入库 %d 条', len(raw), saved)
    return {'ok': True, 'fetched': len(raw), 'saved': saved, 'items': result_items[:30]}


def build_premarket_content(items: list[dict]) -> str:
    """生成盘前资讯推送内容（重大/持仓相关/美股隔夜/宏观）"""
    lines = ['📰 盘前资讯速递', '━━━━━━━━━━━━━━']
    major = [it for it in items if it['level'] == '重大']
    holding = [it for it in items if it['holding_related']]
    us = [it for it in items if it['market'] == '美股']
    if major:
        lines.append('━━ 重大事件 ━━')
        for it in major[:5]:
            lines.append(f"🔴 {it['title']}")
            lines.append(f"   → {it['summary'][:60]}")
    if holding:
        lines.append('━━ 持仓相关 ━━')
        for it in holding[:5]:
            lines.append(f"🟡 {it['title']}")
            lines.append(f"   → {it['summary'][:60]}")
    if us:
        lines.append('━━ 美股/全球 ━━')
        for it in us[:3]:
            lines.append(f"🟢 {it['title']}")
    if not major and not holding and not us:
        lines.append('今日暂无特别重大资讯')
    return chr(10).join(lines)
