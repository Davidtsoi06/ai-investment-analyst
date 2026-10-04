# -*- coding: utf-8 -*-
"""V1.3.0 二期：主题雷达 + 主题历史回溯

- 主题扫描：从本地资讯库窗口内统计各主题（内置 + 用户自定义）的命中情况
  输出：命中数 / 首次出现日期 / 最近日期 / 关联标的 / 代表资讯（可点击）
- 主题回溯：以主题首次出现日为基准，回看关联标的当时位置与之后表现
  （回答"如果当时看到这条消息，会不会有机会"）
"""

import json
import re
from datetime import date, datetime, timedelta

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection
from .logger import get_app_logger

logger = get_app_logger()

# 内置常见主题（可被用户自定义主题扩充）
DEFAULT_THEMES = (
    'AI算力', '数据中心', '液冷', '光模块', '存储芯片', '半导体', '机器人', '人形机器人',
    '固态电池', '新能源车', '光伏', '储能', '氢能', '可控核聚变', '低空经济', '商业航天',
    '卫星互联网', '创新药', '合成生物', '脑机接口', '军工', '黄金', '稀土', '白酒',
    '银行', '券商', '房地产', '电力', '煤炭', '石油', '钻石散热', '培育钻石', '消费电子',
)

# 主题 → 代表标的（人工维护的产业链映射；与资讯中出现的公司名合并使用）
THEME_STOCKS: dict = {
    '钻石散热': [('600172', '黄河旋风', 'A股'), ('301071', '力量钻石', 'A股'), ('002132', '恒星科技', 'A股')],
    '培育钻石': [('600172', '黄河旋风', 'A股'), ('301071', '力量钻石', 'A股')],
    'AI算力': [('000977', '浪潮信息', 'A股'), ('603019', '中科曙光', 'A股'), ('688041', '海光信息', 'A股')],
    '液冷': [('002837', '英维克', 'A股'), ('300811', '铂科新材', 'A股')],
    '光模块': [('300308', '中际旭创', 'A股'), ('002281', '光迅科技', 'A股')],
    '机器人': [('002472', '双环传动', 'A股'), ('688017', '绿的谐波', 'A股')],
    '固态电池': [('300750', '宁德时代', 'A股'), ('002460', '赣锋锂业', 'A股')],
    '低空经济': [('002526', '山东矿机', 'A股'), ('300455', '航天智装', 'A股')],
    '半导体': [('688981', '中芯国际', 'A股'), ('688008', '澜起科技', 'A股')],
    '创新药': [('600276', '恒瑞医药', 'A股'), ('01801', '信达生物', '港股')],
    '军工': [('600760', '中航沈飞', 'A股'), ('000768', '中航西飞', 'A股')],
    '黄金': [('600547', '山东黄金', 'A股'), ('600489', '中金黄金', 'A股')],
    '白酒': [('600519', '贵州茅台', 'A股'), ('000858', '五粮液', 'A股')],
    '券商': [('600030', '中信证券', 'A股'), ('601995', '中金公司', 'A股')],
    '银行': [('600036', '招商银行', 'A股'), ('601398', '工商银行', 'A股')],
    '消费电子': [('002475', '立讯精密', 'A股'), ('002241', '歌尔股份', 'A股')],
    '电力': [('600900', '长江电力', 'A股'), ('600886', '国投电力', 'A股')],
    '新能源车': [('002594', '比亚迪', 'A股'), ('300750', '宁德时代', 'A股')],
    '光伏': [('601012', '隆基绿能', 'A股'), ('002459', '晶澳科技', 'A股')],
    '军工电子': [('688396', '华润微', 'A股')],
}

THEMES_KEY = 'news.my_themes'


def get_my_themes() -> list[str]:
    from .settings_service import get_setting
    try:
        v = get_setting(THEMES_KEY)
        if isinstance(v, str) and v:
            v = json.loads(v)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    except Exception:  # noqa: BLE001
        pass
    return []


def set_my_themes(themes: list[str]) -> list[str]:
    from .settings_service import set_setting
    clean: list[str] = []
    for t in themes:
        t = str(t).strip()
        if t and t not in clean:
            clean.append(t)
    set_setting(THEMES_KEY, clean)
    return clean


def _news_window(days: int) -> list[dict]:
    conn = get_connection()
    try:
        sql = ("SELECT title, summary, source, url, published_at FROM news_cache ")
        params: list = []
        if days and days > 0:
            since = (date.today() - timedelta(days=days)).isoformat()
            sql += "WHERE substr(published_at, 1, 10) >= ? "
            params.append(since)
        sql += "ORDER BY id DESC LIMIT 3000"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _pool_names() -> list[tuple[str, str, str]]:
    """内置池名称 → (symbol, name, market)，用于从资讯标题识别关联标的（不联网）"""
    try:
        from .stock_search_service import _base_pool
        out = []
        for c in _base_pool():
            nm = str(c.get('name') or '').strip()
            if len(nm) >= 2:
                out.append((c['symbol'], nm, c.get('market') or 'A股'))
        return out
    except Exception:  # noqa: BLE001
        return []


def scan_themes(days: int = 180, limit: int = 40) -> dict:
    """主题雷达扫描：命中数 / 首次出现 / 最近出现 / 关联标的 / 代表资讯"""
    items = _news_window(days)
    themes = list(DEFAULT_THEMES) + [t for t in get_my_themes() if t not in DEFAULT_THEMES]
    pool = _pool_names()
    out: list[dict] = []
    for theme in themes:
        hits = []
        for n in items:
            text = (n.get('title') or '') + ' ' + (n.get('summary') or '')
            if theme in text:
                hits.append(n)
        if not hits:
            continue
        dates = sorted((h.get('published_at') or '')[:10] for h in hits if h.get('published_at'))
        # 关联标的：主题映射表 + 资讯标题中出现的池内公司名
        stocks: list[dict] = []
        seen = set()
        for sym, nm, mkt in THEME_STOCKS.get(theme, []):
            if (sym, mkt) not in seen:
                seen.add((sym, mkt))
                stocks.append({'symbol': sym, 'name': nm, 'market': mkt})
        for sym, nm, mkt in pool:
            if len(stocks) >= 8:
                break
            if (sym, mkt) in seen:
                continue
            if any(nm in ((h.get('title') or '') + (h.get('summary') or '')) for h in hits[:40]):
                seen.add((sym, mkt))
                stocks.append({'symbol': sym, 'name': nm, 'market': mkt})
        out.append({
            'theme': theme,
            'count': len(hits),
            'first_date': dates[0] if dates else '',
            'last_date': dates[-1] if dates else '',
            'stocks': stocks[:8],
            'news': [{'title': h.get('title'), 'url': h.get('url'), 'source': h.get('source'),
                      'date': (h.get('published_at') or '')[:10]} for h in hits[:3]],
        })
    out.sort(key=lambda x: (-x['count'], x['first_date']))
    return {'themes': out[:limit], 'my_themes': get_my_themes(), 'window_days': days,
            'news_total': len(items)}


def theme_backtest(theme: str, days: int = 365) -> dict:
    """主题回溯：以主题首次出现日为基准，回看关联标的当时位置与之后表现"""
    theme = (theme or '').strip()
    if not theme:
        return {'ok': False, 'error': '请提供主题名称'}
    scan = scan_themes(days=days, limit=200)
    row = next((t for t in scan['themes'] if t['theme'] == theme), None)
    if row is None:
        return {'ok': False, 'error': f'近 {days} 天资讯中未找到主题「{theme}」' , 'theme': theme}
    first = row['first_date']
    results: list[dict] = []
    for s in (row['stocks'] or [])[:6]:
        try:
            bars = data_fusion.get_kline(s['symbol'], s['market'], 400)
        except Exception:  # noqa: BLE001
            bars = None
        if not bars:
            continue
        base_idx = None
        for i, b in enumerate(bars):
            if str(b.date)[:10] >= first:
                base_idx = i
                break
        if base_idx is None or base_idx >= len(bars):
            continue
        base = float(bars[base_idx].close)
        if base <= 0:
            continue
        last = float(bars[-1].close)
        seg = bars[base_idx:]
        peak = max(float(b.high) for b in seg)
        results.append({
            'symbol': s['symbol'], 'name': s['name'], 'market': s['market'],
            'base_date': str(bars[base_idx].date)[:10], 'base_price': round(base, 3),
            'last_price': round(last, 3),
            'return_pct': round((last / base - 1) * 100, 2),
            'max_gain_pct': round((peak / base - 1) * 100, 2),
        })
    results.sort(key=lambda x: -x['max_gain_pct'])
    return {'ok': True, 'theme': theme, 'first_date': first, 'news': row['news'],
            'items': results, 'window_days': days}
