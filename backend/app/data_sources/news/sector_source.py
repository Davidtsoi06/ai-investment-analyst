# -*- coding: utf-8 -*-
"""V1.3.0：板块热点（热点/板块依据）+ 三期信息源（公告 / 快讯）

实测可用（2026-10）：
- 东财板块行情 push2 clist（行业 t:2 / 概念 t:3；成分股 fs=b:BKxxxx）
- 东财公告 np-anotice-stock（公告是最早期的信号来源）
- 同花顺快讯 news.10jqka.com.cn（快讯早于传统媒体）

均为公开 JSON 接口（不抓取网页 HTML）。
"""

import json
from datetime import datetime

from ..market.http_client import get
from ...models.database import get_connection, utc_now
from ...services.logger import get_app_logger

logger = get_app_logger()

_SECTOR_URL = 'https://push2.eastmoney.com/api/qt/clist/get'
_ANN_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
_THS_URL = 'https://news.10jqka.com.cn/tapp/news/push/stock/'


def fetch_sector_rank(kind: str = 'concept', limit: int = 10) -> list[dict]:
    """板块涨幅榜：kind=industry 行业 / concept 概念 → [{code,name,change_pct,leader,leader_code}]"""
    fs = 'm:90+t:2+f:!50' if kind == 'industry' else 'm:90+t:3+f:!50'
    try:
        text = get(_SECTOR_URL, params={
            'pn': 1, 'pz': max(1, min(limit, 50)), 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f3', 'fs': fs, 'fields': 'f12,f14,f3,f128,f140',
        }, timeout=8.0)
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning('板块行情获取失败(%s): %s', kind, str(e)[:100])
        return []
    diff = ((data.get('data') or {}).get('diff')) or []
    out = []
    for r in diff:
        try:
            chg = float(r.get('f3'))
        except (TypeError, ValueError):
            continue
        out.append({
            'code': str(r.get('f12') or ''),
            'name': str(r.get('f14') or ''),
            'change_pct': chg,
            'leader': str(r.get('f128') or ''),
            'leader_code': str(r.get('f140') or ''),
        })
    return out


def fetch_sector_stocks(sector_code: str, limit: int = 10) -> list[dict]:
    """板块成分股（按涨幅降序）→ [{symbol,name,change_pct,market}]"""
    if not sector_code:
        return []
    try:
        text = get(_SECTOR_URL, params={
            'pn': 1, 'pz': max(1, min(limit, 50)), 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f3', 'fs': f'b:{sector_code}', 'fields': 'f12,f14,f3',
        }, timeout=8.0)
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning('板块成分股获取失败(%s): %s', sector_code, str(e)[:100])
        return []
    diff = ((data.get('data') or {}).get('diff')) or []
    out = []
    for r in diff:
        code = str(r.get('f12') or '').strip()
        name = str(r.get('f14') or '').strip()
        if not code or not name:
            continue
        market = '港股' if (len(code) == 5 and code.startswith('0')) else 'A股'
        try:
            chg = float(r.get('f3'))
        except (TypeError, ValueError):
            chg = 0.0
        out.append({'symbol': code, 'name': name, 'market': market, 'change_pct': chg})
    return out


def _save_news(items: list[dict], source: str) -> int:
    """入库 news_cache（去重靠 content_hash）；region='cn'"""
    if not items:
        return 0
    conn = get_connection()
    saved = 0
    try:
        for it in items:
            title = (it.get('title') or '').strip()
            url = (it.get('url') or '').strip()
            if not title or not url:
                continue
            h = str(abs(hash(title + url)))
            exists = conn.execute('SELECT 1 FROM news_cache WHERE content_hash = ? LIMIT 1', (h,)).fetchone()
            if exists:
                continue
            conn.execute(
                'INSERT INTO news_cache (title, url, source, market, summary, level, content_hash, '
                'published_at, created_at, region, related_stocks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (title, url, source, 'A股/港股', (it.get('summary') or '')[:400], it.get('level') or '一般',
                 h, it.get('published') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 utc_now(), 'cn', '[]'),
            )
            saved += 1
        conn.commit()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning('%s 资讯入库失败: %s', source, str(e)[:120])
    finally:
        conn.close()
    return saved


def fetch_announcements(limit: int = 30) -> int:
    """东财公告（最早期的公司信号）→ 入库"""
    try:
        text = get(_ANN_URL, params={'sr': -1, 'page_size': min(limit, 50), 'page_index': 1,
                                     'ann_type': 'A', 'client_source': 'web'}, timeout=8.0)
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning('公告获取失败: %s', str(e)[:100])
        return 0
    items = []
    for r in ((data.get('data') or {}).get('list') or []):
        title = str(r.get('title') or '').strip()
        code = str(r.get('art_code') or '').strip()
        if not title or not code:
            continue
        names = '、'.join(str(c.get('short_name') or '') for c in (r.get('codes') or [])[:2])
        items.append({
            'title': f'{names}：{title}' if names else title,
            'url': f'https://data.eastmoney.com/notices/detail/{code}.html',
            'summary': title,
            'published': (r.get('notice_date') or '')[:19].replace('T', ' '),
            'level': '中等',
        })
    n = _save_news(items, '东财公告')
    logger.info('公告抓取: %d 条 → 新增 %d 条', len(items), n)
    return n


def fetch_ths_flash(limit: int = 30) -> int:
    """同花顺快讯（早于传统媒体的短讯）→ 入库"""
    try:
        text = get(_THS_URL, params={'page': 1, 'tag': '', 'track': 'website'}, timeout=8.0)
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning('快讯获取失败: %s', str(e)[:100])
        return 0
    items = []
    for r in ((data.get('data') or {}).get('list') or [])[:limit]:
        title = str(r.get('title') or '').strip()
        url = str(r.get('url') or '').strip()
        if not title or not url:
            continue
        try:
            ts = int(r.get('ctime') or r.get('rtime') or 0)
            pub = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts else ''
        except (TypeError, ValueError):
            pub = ''
        items.append({'title': title, 'url': url, 'summary': str(r.get('digest') or '')[:300],
                      'published': pub, 'level': '一般'})
    n = _save_news(items, '同花顺快讯')
    logger.info('快讯抓取: %d 条 → 新增 %d 条', len(items), n)
    return n


def build_hot_entries(quota: int = 3) -> dict:
    """🔥 热点/板块依据：取涨幅前 3 个概念/行业板块 → 各取前若干成分股 → 生成推荐条目"""
    sectors = fetch_sector_rank('concept', 6) + fetch_sector_rank('industry', 4)
    sectors = [s for s in sectors if s.get('code') and s.get('change_pct', 0) > 0][:5]
    if not sectors:
        return {'entries': [], 'notes': ['板块行情不可用或无上涨板块（稍后重试）']}
    from ..market.data_fusion import data_fusion
    entries: list[dict] = []
    seen: set = set()
    for sec in sectors:
        for st in fetch_sector_stocks(sec['code'], 6):
            if len(entries) >= max(1, quota):
                break
            key = (st['symbol'], st['market'])
            if key in seen:
                continue
            seen.add(key)
            try:
                q = data_fusion.get_quote(st['symbol'], st['market'])
            except Exception:  # noqa: BLE001
                q = None
            if q is None or not q.price:
                continue
            price = float(q.price)
            chg = float(st.get('change_pct') or 0)
            if chg > 9.5:  # 已涨停/近乎涨停，追高风险大
                continue
            conf = 62 if sec['change_pct'] >= 3 else 58
            entries.append({
                'symbol': st['symbol'], 'name': st['name'], 'market': st['market'], 'rec_type': '短线',
                'entry_min': round(price * 0.99, 2), 'entry_max': round(price * 1.02, 2),
                'stop_loss': round(price * 0.95, 2), 'target': round(price * 1.06, 2),
                'valuation_min': None, 'valuation_max': None,
                'confidence': conf,
                'logic': f"🔥 热点/板块：{sec['name']} 板块涨幅 {sec['change_pct']:.2f}%（领涨 {sec.get('leader') or '—'}），"
                         f"该股当日 {chg:+.2f}%，板块效应驱动；注意热点持续性",
                'risk_level': '高',
                'price': price,
                'tier': 'rec' if conf >= 60 else 'watch',
                'driver': 'hot',
                'sources': [],
            })
        if len(entries) >= max(1, quota):
            break
    notes = ['热点板块：' + '、'.join(f"{s['name']}({s['change_pct']:+.2f}%)" for s in sectors[:3])] if sectors else []
    return {'entries': entries[:max(1, quota)], 'notes': notes}


def register_extra_news_jobs() -> None:
    """三期信息源定时抓取（公告/快讯，每 30 分钟）"""
    from ...services.scheduler import add_interval_job

    def _job() -> None:
        try:
            fetch_announcements(30)
            fetch_ths_flash(30)
        except Exception as e:  # noqa: BLE001
            logger.error('公告/快讯抓取任务失败: %s', e)

    add_interval_job(_job, minutes=30, job_id='extra_news_fetch')
    logger.info('已注册每 30 分钟公告/快讯抓取任务（三期信息源）')
