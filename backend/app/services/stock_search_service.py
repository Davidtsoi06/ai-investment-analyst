# -*- coding: utf-8 -*-
"""V1.1.3 股票搜索：代码 / 中文名称 / 拼音首字母·全拼（内置索引）+ 东财 suggest 兜底"""

import re
import threading

from ..agents.chat_agent import COMMON_STOCKS
from ..agents.recommend_agent import DEFAULT_CANDIDATES, INDUSTRY_POOLS
from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection

_lock = threading.Lock()
_index: list[dict] | None = None  # [{symbol,name,market,py(全拼小写), initials(首字母小写)}]


def _base_pool() -> list[dict]:
    """内置搜索池：词典行业股 + 蓝筹 + 常见股 + 用户 watchlist/holdings"""
    pool: dict[tuple, dict] = {}
    def add(sym, name, mkt):
        if sym and name:
            pool.setdefault((sym, mkt), {'symbol': sym, 'name': name, 'market': mkt})
    for g in INDUSTRY_POOLS:
        for sym, name, mkt in g['stocks']:
            add(sym, name, mkt)
    for c in DEFAULT_CANDIDATES:
        add(c['symbol'], c['name'], c['market'])
    for name, sym in COMMON_STOCKS.items():
        add(sym, name, 'A股')
    try:
        conn = get_connection()
        try:
            rows = conn.execute('SELECT symbol, name, market FROM watchlist UNION SELECT symbol, name, market FROM holdings').fetchall()
            for r in rows:
                add(r['symbol'], r['name'] or '', r['market'] or '')
        finally:
            conn.close()
    except Exception:
        pass
    return list(pool.values())


def _pinyin_keys(name: str) -> tuple[str, str]:
    """返回 (全拼小写, 首字母小写)；失败返回 ('','')"""
    try:
        from pypinyin import lazy_pinyin
        parts = lazy_pinyin(name)
        return ''.join(parts).lower(), ''.join(p[0] for p in parts if p).lower()
    except Exception:
        return '', ''


def _build_index() -> list[dict]:
    with _lock:
        global _index
        if _index is not None:
            return _index
        out = []
        for c in _base_pool():
            full, ini = _pinyin_keys(c['name'])
            out.append({**c, 'py': full, 'ini': ini})
        _index = out
        return out


def search_stock(kw: str, limit: int = 8) -> list[dict]:
    """按代码/中文/拼音搜索 → [{symbol,name,market}]；零结果返回 []"""
    kw = (kw or '').strip().lower()
    if not kw:
        return []
    results: list[dict] = []
    seen: set = set()

    def add(c: dict, score: int):
        k = (c['symbol'], c['market'])
        if k not in seen:
            seen.add(k)
            results.append({'symbol': c['symbol'], 'name': c['name'], 'market': c['market'], 'score': score})

    # 1) 内置索引：精确代码/名称 > 拼音全拼 > 首字母/子串
    for c in _build_index():
        sym = c['symbol'].lower()
        name = c['name'].lower()
        if kw == sym or kw == name:
            add(c, 0)
        elif name.startswith(kw) or (c.get('py') and c['py'].startswith(kw)):
            add(c, 1)
        elif (c.get('ini') and c['ini'].startswith(kw)) or kw in name:
            add(c, 2)
    # 2) 东财兜底（中文/代码的模糊补全，港股亦可）
    if len(results) < limit and re.fullmatch(r'[\u4e00-\u9fa5\w]{1,20}', kw) and not kw.isascii() or kw.isdigit():
        try:
            from ..data_sources.market.stock_search import search_stocks
            for s in search_stocks(kw, limit - len(results)):
                k = (s['symbol'], s['market'])
                if k not in seen:
                    seen.add(k)
                    results.append({'symbol': s['symbol'], 'name': s['name'], 'market': s['market'], 'score': 3})
        except Exception:
            pass
    results.sort(key=lambda x: x['score'])
    return results[:limit]


def with_price(items: list[dict]) -> list[dict]:
    """给候选补现价（并行拉取 ≤6 只，失败保持 null）"""
    import threading
    def _one(it: dict) -> None:
        try:
            q = data_fusion.get_quote(it['symbol'], it['market'])
            it['price'] = q.price if q and q.price else None
        except Exception:
            it['price'] = None
    ts = [threading.Thread(target=_one, args=(it,), daemon=True) for it in items[:6]]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=5)
    return items
