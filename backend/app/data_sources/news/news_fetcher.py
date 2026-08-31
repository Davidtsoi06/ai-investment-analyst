# -*- coding: utf-8 -*-
"""资讯抓取：东财快讯（A股/港股）+ 新浪滚动（全球/美股参考）"""

import json
import time
from dataclasses import dataclass

from ..market.http_client import get

EASTMONEY_URL = 'https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html'
SINA_URL = 'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=20&page=1'

MARKET_KEYWORDS = {
    '港股': ['港股', '恒生', '香港', '港交所', '南下', '南向'],
    '美股': ['美股', '纳斯达克', '道指', '标普', '美联储', '美国', '欧股'],
    'A股': ['A股', '沪指', '深成指', '创业板', '沪深', '两市', '北向', '证监会'],
}


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    summary: str
    published_at: str
    market: str = 'A股'


def _detect_market(text: str) -> str:
    """按关键词推断资讯市场归属"""
    for market, kws in MARKET_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return market
    return 'A股'


def _fetch_eastmoney() -> list[NewsItem]:
    raw = get(EASTMONEY_URL, encoding='utf-8')
    if '=' in raw:
        raw = raw.split('=', 1)[1]
    data = json.loads(raw)
    items: list[NewsItem] = []
    for row in (data.get('LivesList') or [])[:40]:
        title = (row.get('title') or '').strip()
        if not title:
            continue
        text = title + (row.get('digest') or '')
        items.append(NewsItem(
            title=title,
            url=row.get('url_unique') or row.get('url_w') or '',
            source='东方财富',
            summary=(row.get('digest') or '')[:120],
            published_at=row.get('showtime') or '',
            market=_detect_market(text),
        ))
    return items


def _fetch_sina() -> list[NewsItem]:
    raw = get(SINA_URL, encoding='utf-8', referer='https://finance.sina.com.cn/')
    data = json.loads(raw)
    items: list[NewsItem] = []
    for row in ((data.get('result') or {}).get('data') or [])[:20]:
        title = (row.get('title') or '').strip()
        if not title:
            continue
        text = title + (row.get('intro') or '')
        ts = int(row.get('ctime') or 0)
        published = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else ''
        items.append(NewsItem(
            title=title,
            url=row.get('url') or '',
            source='新浪财经',
            summary=(row.get('intro') or '')[:120],
            published_at=published,
            market=_detect_market(text),
        ))
    return items


def fetch_news() -> list[NewsItem]:
    """并行抓取全部源（单源失败不影响整体）"""
    result: list[NewsItem] = []
    for fn in (_fetch_eastmoney, _fetch_sina):
        try:
            result.extend(fn())
        except Exception:  # noqa: BLE001
            continue
    return result
