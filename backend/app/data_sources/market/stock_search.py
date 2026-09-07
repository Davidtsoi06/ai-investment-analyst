# -*- coding: utf-8 -*-
"""外部股票搜索：东财 suggest 名称 → 代码（智能问答 #8 增强：非持仓股票也能识别）

仅作名称→代码解析，不爬网页；失败返回空列表（不影响主流程）。
"""

import json
import logging
import re

from .http_client import get

logger = logging.getLogger('stock_search')

SEARCH_URL = 'https://searchapi.eastmoney.com/api/suggest/get'
# 东财前端公开固定 token（仅用于 suggest 名称搜索）
SEARCH_TOKEN = 'D43BF722C8E33BDC906FB84D85E326E8'

# 东财 suggest MktNum：0/1 = 沪深A股，116 = 港股
MKT_A = ('0', '1', 0, 1)
MKT_HK = ('116', 116)

# 港股衍生品/权证特征词（正股名不含）
_DERIVATIVE_HINTS = (
    '购', '沽', '牛证', '熊证', '法兴', '摩利', '摩通', '瑞银', '信证', '高盛', '麦格理',
    '中银', '汇丰', '国君', '华泰', '野村', '大和', '海通', '法巴', '瑞信', '星展', '花旗',
    '东亚', '比迪', '荷合', 'CALL', 'PUT',
)
# A 股代码前缀白名单（v1.1.5 放开：沪深主板/创业板/科创板 + 北交所 92/83/87/43 + 场内基金 50/51/56/58/15/16/18）
_A_PREFIXES = ('60', '68', '00', '30', '92', '83', '87', '43', '50', '51', '56', '58', '15', '16', '18')
# 港股正股代码多为 00xxx/01xxx（5 位数字 0 开头）
_HK_RE = re.compile(r'^0\d{4}$')
_SUFFIX_RE = re.compile(r'[-_/／]?(?:W|R|WR|S|B|ADR|SW|Ltd|H股)(?![\u4e00-\u9fa5A-Za-z])')


def normalize_name(name: str) -> str:
    # 去交易所/类别后缀：'小米集团-W' → '小米集团'；'腾讯控股-R' → '腾讯控股'
    return _SUFFIX_RE.sub('', name or '').strip()


def _classify(code: str, name: str) -> str | None:
    """代码/名称 → 市场（A股/港股）；非法或衍生品返回 None"""
    if not code or not name:
        return None
    if any(h in name for h in _DERIVATIVE_HINTS):
        return None  # 权证/衍生品
    if code.isdigit() and len(code) == 6 and code.startswith(_A_PREFIXES):
        return 'A股'
    if _HK_RE.match(code):
        return '港股'
    return None


def _dedup(items: list, limit: int) -> list:
    out: list = []
    seen: set = set()
    for it in items:
        k = (it.get('market'), it.get('symbol'))
        if k not in seen:
            seen.add(k)
            out.append(it)
        if len(out) >= limit:
            break
    return out


def _eastmoney_suggest(kw: str, want: int) -> list:
    """东财 suggest（主源：沪深京+港股，MktNum 明确）"""
    try:
        text = get(SEARCH_URL, params={
            'input': kw,
            'type': '14',
            'token': SEARCH_TOKEN,
            'count': str(min(max(want, 1), 10)),
        }, timeout=6.0)
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning('东财搜索失败 %s: %s', kw, str(e)[:80])
        return []
    rows = (data.get('QuotationCodeTable') or {}).get('Data') or []
    out = []
    for r in rows:
        code = str(r.get('Code') or '').strip()
        name = str(r.get('Name') or '').strip()
        mkt = r.get('MktNum')
        market = _classify(code, name) if (mkt in MKT_A or mkt in MKT_HK) else None
        if market:
            out.append({'symbol': code, 'name': normalize_name(name), 'market': market})
    return out


def _tencent_suggest(kw: str, want: int) -> list:
    """腾讯 smartbox（备用源；覆盖沪深京+港股+场内基金）"""
    try:
        text = get('https://smartbox.gtimg.cn/s3/',
                   params={'v': '2', 'q': kw, 't': 'all'}, timeout=6.0, encoding='utf-8')
    except Exception as e:  # noqa: BLE001
        logger.warning('腾讯搜索失败 %s: %s', kw, str(e)[:80])
        return []
    try:
        m = re.search(r'v_hint="(.*)"', text or '', re.S)
        raw = m.group(1) if m else ''
        if not raw or raw == 'N':
            return []
        # smartbox 返回 ASCII + unicode 转义文本，用 json 解码一次
        raw = json.loads('"' + raw.replace('\\"', '"') + '"')
    except Exception as e:  # noqa: BLE001
        logger.warning('腾讯搜索解析失败 %s: %s', kw, str(e)[:80])
        return []
    out = []
    for part in raw.split('^'):
        seg = part.split('~')
        if len(seg) < 3:
            continue
        pre, code, name = seg[0].strip(), seg[1].strip(), seg[2].strip()
        if pre not in ('sh', 'sz', 'bj', 'hk'):
            continue
        market = _classify(code, name)
        if market:
            out.append({'symbol': code, 'name': normalize_name(name), 'market': market})
    return out


def _sina_suggest(kw: str, want: int) -> list:
    """新浪 suggest（备用源2；覆盖沪深京+港股）"""
    try:
        text = get('https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15&key=' + kw,
                   timeout=6.0, encoding='gbk')
    except Exception as e:  # noqa: BLE001
        logger.warning('新浪搜索失败 %s: %s', kw, str(e)[:80])
        return []
    try:
        m = re.search(r'"(.*)"', text or '', re.S)
        raw = m.group(1) if m else ''
        if not raw:
            return []
    except Exception as e:  # noqa: BLE001
        logger.warning('新浪搜索解析失败 %s: %s', kw, str(e)[:80])
        return []
    out = []
    for item in raw.split(';'):
        f = item.split(',')
        if len(f) < 4:
            continue
        name, code, full = f[0].strip(), f[2].strip(), f[3].strip()
        pre = full[:2] if len(full) >= 2 and full[:2] in ('sh', 'sz', 'bj', 'hk') else ''
        if not pre:
            continue
        market = _classify(code, name)
        if market:
            out.append({'symbol': code, 'name': normalize_name(name), 'market': market})
    return out


def search_stocks(keyword: str, limit: int = 5) -> list[dict]:
    """按名称/代码关键词搜索股票 → [{symbol, name, market}]（v1.1.5 多源兜底：
    东财 suggest 主源，无结果自动切换 腾讯 smartbox / 新浪 suggest）；全部失败返回 []"""
    kw = (keyword or '').strip()
    if not kw or len(kw) > 20:
        return []
    items: list = []
    for fn in (_eastmoney_suggest, _tencent_suggest, _sina_suggest):
        try:
            items.extend(fn(kw, limit))
        except Exception:  # noqa: BLE001
            continue
        if _dedup(items, limit):
            break
    return _dedup(items, limit)
