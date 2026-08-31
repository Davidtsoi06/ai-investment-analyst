# -*- coding: utf-8 -*-
"""市场快照采集（S12）：指数 / 板块 / 成交额 / 情绪指标

数据源（免费接口，多源容错，任一来源失败不影响整体）：
  - 指数行情：腾讯 qt.gtimg.cn（A股 4 大指数 + 港股 3 大指数）
  - A股 情绪与成交额：东方财富 ulist.np（上涨/下跌/平盘/涨停/跌停家数 + 两市成交额）
  - A股 行业板块涨跌：东方财富 clist（领涨/领跌 Top N，含主力净流入）
  - 港股 主板成交额：东方财富 100.HSI f48（港股板块无免费来源，快照中缺省）

collect_snapshot(market) 返回统一快照 dict：
  {market, indices:[{symbol,name,price,change_pct,change,open,high,low,prev_close,amount,volume,timestamp}],
   breadth:{up,down,flat,limit_up,limit_down,turnover} | None,
   boards:{gainers:[{code,name,change_pct,turnover_rate,main_inflow,up,down}], losers:[...]} | None,
   turnover, timestamp}
"""

import json
from datetime import datetime

from .http_client import get

TENCENT_URL = 'https://qt.gtimg.cn/q='
EM_ULIST_URL = 'https://push2.eastmoney.com/api/qt/ulist.np/get'
EM_CLIST_URL = 'https://push2.eastmoney.com/api/qt/clist/get'
EM_STOCK_URL = 'https://push2.eastmoney.com/api/qt/stock/get'

# 指数代码（腾讯）：A股 4 大 + 港股 3 大
A_INDICES = [
    ('sh000001', '上证指数'),
    ('sz399001', '深证成指'),
    ('sz399006', '创业板指'),
    ('sh000300', '沪深300'),
]
HK_INDICES = [
    ('hkHSI', '恒生指数'),
    ('hkHSTECH', '恒生科技指数'),
    ('hkHSCEI', '国企指数'),
]

# 东方财富 secid：A股 两市（沪 1.000001 / 深 0.399001）；港股主板成交额 100.HSI
A_BREADTH_SECIDS = '1.000001,0.399001'
HK_TURNOVER_SECID = '100.HSI'

_BOARD_FS = 'm:90+t:2+f:!50'  # A股 行业板块
_BOARD_FIELDS = 'f2,f3,f8,f12,f14,f62,f104,f105,f106'


def _f(row: dict, key: str, default=0.0):
    """东财字段取值容错（'-' / None / 缺省 → default）"""
    try:
        v = row.get(key)
        if v is None or v == '-':
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def get_index_quotes(market: str) -> list[dict]:
    """指数实时行情（腾讯）：返回统一 dict 列表；来源异常返回 []"""
    codes = A_INDICES if market == 'A股' else (HK_INDICES if market == '港股' else [])
    if not codes:
        return []
    try:
        text = get(TENCENT_URL + ','.join(c for c, _ in codes), encoding='gbk')
    except Exception:
        return []
    result: list[dict] = []
    for line in text.strip().split(';'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        sym = line.split('=')[0].replace('v_', '')
        name = dict(codes).get(sym, '')
        parts = line.split('=')[1].strip('"').split('~')
        if len(parts) < 38 or not parts[3]:
            continue
        price = _f({'p': parts[3]}, 'p')
        if price <= 0:
            continue
        prev_close = _f({'p': parts[4]}, 'p') or price
        # 腾讯字段：A股指数 [31]涨跌额 [32]涨跌幅% [33]最高 [34]最低 [37]成交额(万)；港股指数 [37] 为成交量（无成交额）
        change = _f({'p': parts[31]}, 'p') if len(parts) > 31 else price - prev_close
        change_pct = _f({'p': parts[32]}, 'p') if len(parts) > 32 else (price / prev_close - 1) * 100
        amount = _f({'p': parts[37]}, 'p') * 10000 if len(parts) > 37 else 0.0  # 万 -> 元（仅A股指数有效）
        result.append({
            'symbol': sym,
            'name': parts[1] or name,
            'market': market,
            'price': round(price, 3),
            'change': round(change, 2),
            'change_pct': round(change_pct, 2),
            'open': round(_f({'p': parts[5]}, 'p'), 3) if len(parts) > 5 else round(price, 3),
            'high': round(_f({'p': parts[33]}, 'p'), 3) if len(parts) > 33 else round(price, 3),
            'low': round(_f({'p': parts[34]}, 'p'), 3) if len(parts) > 34 else round(price, 3),
            'prev_close': round(prev_close, 3),
            'volume': _f({'p': parts[36]}, 'p') if len(parts) > 36 else 0.0,  # 手
            'amount': round(amount, 2),
            'timestamp': parts[30] if len(parts) > 30 and parts[30] else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
    return result


def get_a_breadth() -> dict | None:
    """A股 市场情绪：上涨/下跌/平盘/涨停/跌停家数 + 两市成交额（元）"""
    try:
        text = get(EM_ULIST_URL, params={
            'fltt': 2,
            'secids': A_BREADTH_SECIDS,
            'fields': 'f2,f3,f6,f12,f14,f104,f105,f106,f107,f108',
        })
        rows = (json.loads(text).get('data') or {}).get('diff') or []
        if not rows:
            return None
        up = int(sum(_f(r, 'f104') for r in rows))
        down = int(sum(_f(r, 'f105') for r in rows))
        flat = int(sum(_f(r, 'f106') for r in rows))
        limit_up = int(sum(_f(r, 'f107') for r in rows))
        limit_down = int(sum(_f(r, 'f108') for r in rows))
        turnover = round(sum(_f(r, 'f6') for r in rows), 2)
        return {
            'up': up, 'down': down, 'flat': flat,
            'limit_up': limit_up, 'limit_down': limit_down,
            'turnover': turnover,
        }
    except Exception:
        return None


def _get_boards(po: int, limit: int) -> list[dict]:
    """行业板块列表（po=1 领涨 / po=0 领跌），单次失败返回 []"""
    try:
        text = get(EM_CLIST_URL, params={
            'pn': 1, 'pz': limit, 'po': po, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f3', 'fs': _BOARD_FS, 'fields': _BOARD_FIELDS,
        })
        rows = (json.loads(text).get('data') or {}).get('diff') or []
        items: list[dict] = []
        for r in rows:
            items.append({
                'code': str(r.get('f12') or ''),
                'name': str(r.get('f14') or ''),
                'change_pct': round(_f(r, 'f3'), 2),
                'turnover_rate': round(_f(r, 'f8'), 2),
                'main_inflow': round(_f(r, 'f62'), 2),  # 主力净流入（元）
                'up': int(_f(r, 'f104')),
                'down': int(_f(r, 'f105')),
            })
        return [it for it in items if it['name']]
    except Exception:
        return []


def get_a_boards(limit: int = 8) -> dict:
    """A股 行业板块：领涨/领跌 Top N；任一失败时对应列表为空"""
    return {
        'gainers': _get_boards(1, limit),
        'losers': _get_boards(0, limit),
    }


def get_hk_turnover() -> float | None:
    """港股主板成交额（东财 100.HSI f48，元）；失败返回 None"""
    try:
        text = get(EM_STOCK_URL, params={
            'secid': HK_TURNOVER_SECID,
            'fields': 'f43,f48,f58,f60',
        })
        data = (json.loads(text).get('data') or {})
        v = data.get('f48')
        if v is None or v == '-':
            return None
        return round(float(v), 2)
    except Exception:
        return None


def collect_snapshot(market: str) -> dict:
    """采集某市场完整快照（容错：各部分独立失败，缺失置 None/[]）"""
    indices = get_index_quotes(market)
    snapshot: dict = {
        'market': market,
        'indices': indices,
        'breadth': None,
        'boards': None,
        'turnover': None,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if market == 'A股':
        snapshot['breadth'] = get_a_breadth()
        snapshot['boards'] = get_a_boards(8)
        if snapshot['breadth']:
            snapshot['turnover'] = snapshot['breadth']['turnover']
    elif market == '港股':
        snapshot['turnover'] = get_hk_turnover()
    return snapshot
