# -*- coding: utf-8 -*-
"""V1.1.1 N3 海外财经资讯：多源容错抓取（RSS/JSON 标准接口）→ DeepSeek 标题/简述中文翻译 → 入库

地区：美国(CNBC/MarketWatch)、英国(BBC)、日本(NHK World)、韩国(韩联社中文，免翻译)
网络不可达的源自动跳过（不阻塞）；展示为中文标题+一句话简述，点击跳原文网站（不翻译全文）。
"""

import hashlib
import json
import re
import time
from datetime import datetime
import xml.etree.ElementTree as ET

from ..market.http_client import get
from ...models.database import get_connection, utc_now
from ...services.logger import get_agent_logger

logger = get_agent_logger()

UA_HINT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36'

# region: 用于 UI 分区的地区键；lang: zh 免翻译
SOURCES = [
    {'region': '美国', 'name': 'CNBC', 'lang': 'en', 'url': 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114', 'kind': 'rss'},
    {'region': '美国', 'name': 'MarketWatch', 'lang': 'en', 'url': 'https://feeds.marketwatch.com/marketwatch/topstories/', 'kind': 'rss'},
    {'region': '英国', 'name': 'BBC Business', 'lang': 'en', 'url': 'https://feeds.bbci.co.uk/news/business/rss.xml', 'kind': 'rss'},
    {'region': '日本', 'name': 'NHK World', 'lang': 'en', 'url': 'https://www3.nhk.or.jp/nhkworld/data/en/news/all.json', 'kind': 'json'},
    {'region': '韩国', 'name': '韩联社中文', 'lang': 'zh', 'url': 'https://cn.yna.co.kr/RSS/news.xml', 'kind': 'rss'},
]

PER_SOURCE_LIMIT = 15


def _fetch_rss(url: str) -> list[dict]:
    text = get(url, timeout=12, retries=2)
    root = ET.fromstring(text)
    items = []
    for it in root.findall('.//item')[:PER_SOURCE_LIMIT]:
        t = (it.findtext('title') or '').strip()
        link = (it.findtext('link') or '').strip()
        if not t or not link:
            continue
        pub = (it.findtext('pubDate') or it.findtext('dc:date') or '').strip()
        items.append({'title': t, 'url': link, 'published': pub,
                      'desc': (it.findtext('description') or '')[:400]})
    return items


def _fetch_json(url: str) -> list[dict]:
    text = get(url, timeout=12, retries=2)
    data = json.loads(text)
    arr = data if isinstance(data, list) else (data.get('items') or data.get('news') or [])
    items = []
    for it in arr[:PER_SOURCE_LIMIT]:
        t = (it.get('title') or '').strip()
        link = (it.get('link') or it.get('url') or '').strip()
        if not t:
            continue
        items.append({'title': t, 'url': link,
                      'published': it.get('date') or it.get('pubDate') or '',
                      'desc': (it.get('description') or it.get('summary') or '')[:400]})
    return items


def _translate_batch(items: list[dict]) -> None:
    """把非中文标题/简述翻译为中文（就地更新 title/desc_zh）。失败静默（保留原文）。"""
    from ...services.llm_client import chat
    from ...services.settings_service import ai_key_configured
    if not ai_key_configured():
        for it in items:
            it['translated'] = False
        return
    try:
        chunk = items[:10]
        src = '\n'.join(f"{i + 1}. {it['title']} —— {it.get('desc', '')[:120]}" for i, it in enumerate(chunk))
        prompt = (
            '把以下海外财经新闻逐条翻译成简洁中文：标题直译（保留专有名词原文）、'
            '一句话简述意译（不超过 60 字，不要编造原文没有的信息）。\n'
            '只输出 JSON 数组，不要任何其他文字，格式：'
            '[{"i":1,"title":"中文标题","summary":"中文简述"}, ...]\n\n' + src
        )
        text = chat([{'role': 'user', 'content': prompt}], temperature=0.2, max_tokens=2000)
        fence = chr(96) * 3
        text = re.sub(r'^\\s*' + fence + r'json\\s*|' + fence + r'\\s*$', '', text.strip())
        data = json.loads(text)
        for row in data:
            try:
                idx = int(row.get('i')) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(chunk):
                chunk[idx]['title_zh'] = (row.get('title') or '').strip()
                chunk[idx]['summary_zh'] = (row.get('summary') or '').strip()
        for it in chunk:
            it['translated'] = bool(it.get('title_zh'))
    except Exception as e:  # noqa: BLE001
        logger.warning('海外资讯翻译失败（保留原文）: %s', str(e)[:100])
        for it in items:
            it['translated'] = False


def _save_items(items: list[dict], source_name: str, region: str) -> int:
    """去重入库（content_hash）；中文展示字段：title_zh/title；desc_zh/desc"""
    conn = get_connection()
    saved = 0
    try:
        for it in items:
            title_zh = it.get('title_zh') or it.get('title') or ''
            summary_zh = it.get('summary_zh') or it.get('desc') or ''
            url = it.get('url') or ''
            if not title_zh:
                continue
            h = hashlib.md5((title_zh + url).encode('utf-8')).hexdigest()
            cur = conn.execute(
                '''INSERT OR IGNORE INTO news_cache
                (title, url, source, market, summary, level, content_hash, published_at, created_at, region, related_stocks)
                VALUES (?, ?, ?, ?, ?, '一般', ?, ?, ?, ?, NULL)''',
                (title_zh, url, source_name + '(海外)', region, summary_zh,
                 h, it.get('published') or '', utc_now(), region),
            )
            if cur.rowcount > 0:
                saved += 1
    finally:
        conn.close()
    return saved


def collect_overseas() -> dict:
    """抓取全部海外源 → 翻译 → 入库；返回汇总 {ok, fetched, saved, failed_sources, items}"""
    fetched = 0
    saved = 0
    failed: list[str] = []
    samples: list[dict] = []
    for src in SOURCES:
        try:
            if src['kind'] == 'rss':
                items = _fetch_rss(src['url'])
            else:
                items = _fetch_json(src['url'])
            if not items:
                failed.append(src['name'])
                continue
            if src['lang'] != 'zh':
                _translate_batch(items)
            n = _save_items(items, src['name'], src['region'])
            fetched += len(items)
            saved += n
            for it in items[:2]:
                samples.append({
                    'region': src['region'], 'source': src['name'],
                    'title': it.get('title_zh') or it.get('title', ''),
                    'url': it.get('url', ''),
                    'translated': it.get('translated', src['lang'] == 'zh'),
                })
        except Exception as e:  # noqa: BLE001
            logger.warning('海外源 %s 抓取失败（跳过）: %s', src['name'], str(e)[:100])
            failed.append(src['name'])
    logger.info('海外资讯抓取完成: 抓取 %d 条 → 新增 %d 条；失败源: %s', fetched, saved, '、'.join(failed) or '无')
    return {'ok': True, 'fetched': fetched, 'saved': saved,
            'failed_sources': failed, 'items': samples[:10]}


def register_overseas_jobs() -> None:
    """8:00~22:00 每 30 分钟抓一轮（多源容错）"""
    from apscheduler.triggers.cron import CronTrigger
    from ...services.scheduler import scheduler

    def _job() -> None:
        try:
            collect_overseas()
        except Exception as e:  # noqa: BLE001
            logger.error('定时海外资讯抓取失败: %s', e)

    scheduler.add_job(_job, CronTrigger(hour='8-22', minute='*/30'),
                      id='overseas_news', replace_existing=True)
    logger.info('海外资讯定时任务已注册（8:00-22:00 每 30 分钟）')
